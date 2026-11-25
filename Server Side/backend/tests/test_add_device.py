"""
Adding a device needs only a name and an appliance type.

The sensor ID is generated and must never clash inside a home: the table has a unique
key on (home_id, entity_id), so a clash used to surface as a bare 500.
"""
import inspect

from app.routers import devices
from app.routers.devices import MAX_DEVICE_NAME, _SENSOR_ID_OK, _derive_entity_ids, unique_entity_ids


class TestGeneratedSensorIds:

    def test_first_device_of_a_kind_uses_the_publisher_convention(self):
        ids = unique_entity_ids("Kitchen Kettle", "kettle", set())
        assert ids == {
            "entity_id": "kettle_current_consumption",
            "power_entity_id": "kettle_current_consumption",
            "switch_entity_id": "kettle_switch_state",
        }

    def test_a_second_device_of_the_same_kind_gets_its_own_id(self):
        taken = {"kettle_current_consumption"}
        assert unique_entity_ids("Office kettle", "kettle", taken)["entity_id"] == "kettle_2_current_consumption"
        taken.add("kettle_2_current_consumption")
        ids = unique_entity_ids("Garage kettle", "kettle", taken)
        assert ids["entity_id"] == "kettle_3_current_consumption"
        assert ids["switch_entity_id"] == "kettle_3_switch_state"

    def test_ids_of_removed_devices_are_not_reused(self):
        """`taken` includes removed devices: their rows (and unique keys) are still there."""
        taken = {"toaster_current_consumption", "toaster_2_current_consumption"}
        assert unique_entity_ids("Toaster", "toaster", taken)["entity_id"] == "toaster_3_current_consumption"

    def test_unknown_type_falls_back_to_the_device_name(self):
        assert unique_entity_ids("Fish Tank Heater!", "other", set())["entity_id"] == "fish_tank_heater_current_consumption"
        assert unique_entity_ids("  ", "other", set())["entity_id"] == "device_current_consumption"
        assert unique_entity_ids("  ", None, {"device_current_consumption"})["entity_id"] == "device_2_current_consumption"

    def test_aliases_share_one_stem(self):
        a = unique_entity_ids("Washer", "washing_machine", set())["entity_id"]
        b = unique_entity_ids("Washer", "washingmachine", set())["entity_id"]
        assert a == b == "washing_machine_current_consumption"

    def test_generated_ids_are_valid_sensor_ids(self):
        for key in ("kettle", "washing_machine", "coffeemachine", "gaming_console", "tv", "water_purifier", "other"):
            assert _SENSOR_ID_OK.match(unique_entity_ids("Some device", key, set())["entity_id"])

    def test_the_old_helper_still_answers_the_same_for_a_first_device(self):
        assert _derive_entity_ids("Kettle", "kettle") == unique_entity_ids("Kettle", "kettle", set())


class TestSensorIdRule:

    def test_accepts_home_assistant_style_names(self):
        for ok in ("sensor.kettle_3f8a1c", "kettle_current_consumption", "switch.tapo-p110:1", "A1"):
            assert _SENSOR_ID_OK.match(ok), ok

    def test_rejects_spaces_markup_and_overlong_values(self):
        for bad in ("my kettle", "<script>", "kettle/1", "", "x" * 129, "kettle;drop"):
            assert not _SENSOR_ID_OK.match(bad), bad


class TestEndpointContract:

    def test_clashes_are_answered_with_409_not_500(self):
        src = inspect.getsource(devices.add_device)
        assert "IntegrityError" in src and "status_code=409" in src

    def test_name_is_required_and_bounded(self):
        src = inspect.getsource(devices.add_device)
        assert "Give the device a name." in src and "MAX_DEVICE_NAME" in src
        assert MAX_DEVICE_NAME == 60
