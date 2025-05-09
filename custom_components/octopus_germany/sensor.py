"""
This module provides integration with Octopus Germany for Home Assistant.

It defines the coordinator and sensor entities to fetch and display
electricity price information.
"""

import logging
from typing import Any, Dict

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
    SensorDeviceClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Octopus Germany price sensor from a config entry."""
    # Using existing coordinator from hass.data[DOMAIN] to avoid duplicate API calls
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    account_number = data["account_number"]

    # Wait for coordinator refresh if needed
    if coordinator.data is None:
        _LOGGER.debug("No data in coordinator, triggering refresh")
        await coordinator.async_refresh()

    # Debug log to see the complete data structure
    if coordinator.data:
        _LOGGER.debug("Coordinator data keys: %s", coordinator.data.keys())
        if account_number in coordinator.data:
            account_data = coordinator.data[account_number]
            _LOGGER.debug(
                "Account data keys for %s: %s", account_number, account_data.keys()
            )

            # Log product information
            if "products" in account_data:
                _LOGGER.debug("Products found: %s", account_data["products"])
            else:
                _LOGGER.warning(
                    "No 'products' key in account_data for account %s", account_number
                )

    # Initialize entities list
    entities = []

    # Always add the electricity price sensor if we have product data
    if (
        coordinator.data
        and account_number in coordinator.data
        and coordinator.data[account_number].get("products")
    ):
        _LOGGER.debug(
            "Creating electricity price sensor for account %s", account_number
        )
        entities.append(OctopusElectricityPriceSensor(account_number, coordinator))
    else:
        _LOGGER.warning(
            "Not creating electricity price sensor due to missing product data for account %s",
            account_number,
        )
        if coordinator.data:
            if account_number not in coordinator.data:
                _LOGGER.error(
                    "Account %s missing from coordinator data", account_number
                )
            elif not coordinator.data[account_number].get("products"):
                _LOGGER.error(
                    "No product data available for account %s", account_number
                )

    # Only add entities if we have any
    if entities:
        _LOGGER.debug(
            "Adding %d entities: %s",
            len(entities),
            [type(e).__name__ for e in entities],
        )
        async_add_entities(entities)
    else:
        _LOGGER.warning("No entities to add for account %s", account_number)


class OctopusElectricityPriceSensor(CoordinatorEntity, SensorEntity):
    """Sensor for Octopus Germany electricity price."""

    def __init__(self, account_number, coordinator) -> None:
        """Initialize the electricity price sensor."""
        super().__init__(coordinator)

        self._account_number = account_number
        self._attr_name = f"Octopus {account_number} Electricity Price"
        self._attr_unique_id = f"octopus_{account_number}_electricity_price"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = "€/kWh"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_has_entity_name = False
        self._attributes = {}

        # Initialize attributes right after creation
        self._update_attributes()

    @property
    def native_value(self) -> float:
        """Return the current electricity price."""
        if (
            not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
            or self._account_number not in self.coordinator.data
        ):
            _LOGGER.warning("No valid coordinator data found for price sensor")
            return None

        account_data = self.coordinator.data[self._account_number]
        products = account_data.get("products", [])

        if not products:
            _LOGGER.warning("No products found in coordinator data")
            return None

        # Find the current valid product (assuming products are ordered by validity)
        for product in products:
            # Try to get the gross_rate as a float
            try:
                # The grossRate might be a string or a number, handle both cases
                gross_rate_str = product.get("grossRate", "0")
                gross_rate = float(gross_rate_str)

                # Convert from cents to EUR
                gross_rate_eur = gross_rate / 100.0

                _LOGGER.debug(
                    "Found price: %s cents = %s EUR for product %s",
                    gross_rate_str,
                    gross_rate_eur,
                    product.get("code", "Unknown"),
                )

                return gross_rate_eur
            except (ValueError, TypeError) as e:
                _LOGGER.warning(
                    "Failed to convert price for product %s: %s - %s",
                    product.get("code", "Unknown"),
                    product.get("grossRate", "Unknown"),
                    str(e),
                )
                continue

        _LOGGER.warning("No valid price found in any product")
        return None

    def _update_attributes(self) -> None:
        """Update the internal attributes dictionary."""
        # Default empty attributes
        default_attributes = {
            "code": "Unknown",
            "name": "Unknown",
            "description": "Unknown",
            "type": "Unknown",
            "valid_from": "Unknown",
            "valid_to": "Unknown",
            "properties": [],
        }

        # Check if coordinator has valid data
        if (
            not self.coordinator
            or not self.coordinator.data
            or not isinstance(self.coordinator.data, dict)
        ):
            _LOGGER.debug("No valid data structure in coordinator")
            self._attributes = default_attributes
            return

        # Check if account number exists in the data
        if self._account_number not in self.coordinator.data:
            _LOGGER.debug(
                "Account %s not found in coordinator data", self._account_number
            )
            self._attributes = default_attributes
            return

        # Process data from the coordinator
        account_data = self.coordinator.data[self._account_number]
        products = account_data.get("products", [])

        # Get properties information
        properties_info = []
        account_obj = account_data.get("account", {})
        all_properties = account_obj.get("allProperties", [])

        for prop in all_properties:
            property_info = {"id": prop.get("id", "Unknown"), "electricity_malos": []}

            for malo in prop.get("electricityMalos", []):
                malo_info = {
                    "malo_number": malo.get("maloNumber", "Unknown"),
                    "melo_number": malo.get("meloNumber", "Unknown"),
                    "reference_consumption": malo.get(
                        "referenceConsumption", "Unknown"
                    ),
                    "agreements": [],
                }

                # Add meter information if available
                if malo.get("meter"):
                    meter = malo.get("meter", {})
                    malo_info["meter"] = {
                        "id": meter.get("id", "Unknown"),
                        "meter_type": meter.get("meterType", "Unknown"),
                        "number": meter.get("number", "Unknown"),
                        "should_receive_smart_meter_data": meter.get(
                            "shouldReceiveSmartMeterData", False
                        ),
                        "submit_meter_reading_url": meter.get(
                            "submitMeterReadingUrl", ""
                        ),
                    }

                # Add agreements information
                for agreement in malo.get("agreements", []):
                    agreement_info = {
                        "valid_from": agreement.get("validFrom", "Unknown"),
                        "valid_to": agreement.get("validTo", "Unknown"),
                        "product": {},
                    }

                    if agreement.get("product"):
                        product = agreement.get("product", {})
                        agreement_info["product"] = {
                            "code": product.get("code", "Unknown"),
                            "description": product.get("description", ""),
                            "full_name": product.get("fullName", ""),
                        }

                    malo_info["agreements"].append(agreement_info)

                property_info["electricity_malos"].append(malo_info)

            properties_info.append(property_info)

        if not products:
            self._attributes = {**default_attributes, "properties": properties_info}
            return

        # Find the current valid product
        for product in products:
            # Extract attribute values from the product
            product_attributes = {
                "code": product.get("code", "Unknown"),
                "name": product.get("name", "Unknown"),
                "description": product.get("description", "Unknown"),
                "type": product.get("type", "Unknown"),
                "valid_from": product.get("validFrom", "Unknown"),
                "valid_to": product.get("validTo", "Unknown"),
                "properties": properties_info,
            }

            # Add any additional information from account data
            product_attributes["malo_number"] = account_data.get(
                "malo_number", "Unknown"
            )
            product_attributes["melo_number"] = account_data.get(
                "melo_number", "Unknown"
            )

            # Add electricity balance if available
            if "electricity_balance" in account_data:
                product_attributes["electricity_balance"] = (
                    f"{account_data['electricity_balance']:.2f} €"
                )

            self._attributes = product_attributes
            # We just use the first product for now
            break

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_attributes()
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes for the sensor."""
        return self._attributes

    async def async_update(self) -> None:
        """Update the entity."""
        await super().async_update()
        self._update_attributes()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return (
            self.coordinator is not None
            and self.coordinator.last_update_success
            and isinstance(self.coordinator.data, dict)
            and self._account_number in self.coordinator.data
        )
