from unittest.mock import patch, AsyncMock
import pytest
from src.paragraph.repository import ParagraphRepository

@pytest.fixture
def mock_send_xml_over_ishd():
    # Dlya sebya: osnovnoy shag (mock send xml over ishd).
    with patch('src.ishd.client.IshdClient.send_xml_over_ishd', new_callable=AsyncMock) as mock:
        yield mock

@pytest.fixture
def repo():
    # Dlya sebya: osnovnoy shag (repo).
    return ParagraphRepository()

@pytest.mark.asyncio
async def test_create_user_dict_v1(mock_send_xml_over_ishd, repo):
    # Dlya sebya: proverka scenariya "test create user dict v1".
    mock_send_xml_over_ishd.return_value = {"status": "ok", "message": "User dictionary created successfully"}
    result = await repo.create_user_dict_v1()
    assert result == {"status": "ok", "message": "User dictionary created successfully"}
    mock_send_xml_over_ishd.assert_called_once()

@pytest.mark.asyncio
async def test_remove_user_dict(mock_send_xml_over_ishd, repo):
    # Dlya sebya: proverka scenariya "test remove user dict".
    mock_send_xml_over_ishd.return_value = {"status": "ok", "message": "User dictionary removed successfully"}
    result = await repo.remove_user_dict()
    assert result == {"status": "ok", "message": "User dictionary removed successfully"}
    mock_send_xml_over_ishd.assert_called_once()

@pytest.mark.asyncio
async def test_query_user_dict(mock_send_xml_over_ishd, repo):
    # Dlya sebya: proverka scenariya "test query user dict".
    mock_send_xml_over_ishd.return_value = {"status": "ok", "data": {"key": "value"}}
    result = await repo.query_user_dict()
    assert result == {"status": "ok", "data": {"key": "value"}}
    mock_send_xml_over_ishd.assert_called_once()

@pytest.mark.asyncio
async def test_create_user_dict_v1_error(mock_send_xml_over_ishd, repo):
    # Dlya sebya: proverka scenariya "test create user dict v1 error".
    mock_send_xml_over_ishd.side_effect = Exception("Ошибка ИШД")
    result = await repo.create_user_dict_v1()
    assert result == {"status": "fail", "message": "Ошибка ИШД"}
    mock_send_xml_over_ishd.assert_called_once()
