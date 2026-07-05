from datasources.paid_mock import MockSantimentClient


def test_mock_client_flags_output_as_mock():
    client = MockSantimentClient()

    social = client.get_social_volume("BTC")
    dev = client.get_dev_activity("BTC")

    assert social["is_mock"] is True
    assert social["symbol"] == "BTC"
    assert dev["is_mock"] is True
