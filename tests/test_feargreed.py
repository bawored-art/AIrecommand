from unittest.mock import MagicMock

from datasources.feargreed import FearGreedClient


def test_get_latest_parses_value_and_classification(tmp_cache, mock_json_response):
    client = FearGreedClient(cache=tmp_cache, max_retries=1)
    client.session = MagicMock()
    client.session.request.return_value = mock_json_response({
        "data": [{"value": "23", "value_classification": "Extreme Fear", "timestamp": "1783209600"}],
    })

    result = client.get_latest()

    assert result["value"] == 23
    assert result["classification"] == "Extreme Fear"
    assert result["timestamp"] == "1783209600"


def test_get_latest_empty_data_returns_empty_dict(tmp_cache, mock_json_response):
    client = FearGreedClient(cache=tmp_cache, max_retries=1)
    client.session = MagicMock()
    client.session.request.return_value = mock_json_response({"data": []})

    assert client.get_latest() == {}
