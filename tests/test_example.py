import pytest


def test_example():
    """테스트 예시"""
    assert 1 + 1 == 2


@pytest.mark.asyncio
async def test_async_example():
    """비동기 테스트 예시"""
    result = 1 + 1
    assert result == 2
