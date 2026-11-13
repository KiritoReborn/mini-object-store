import asyncio
from io import BytesIO

import pytest
from starlette.datastructures import UploadFile


@pytest.mark.parametrize("size,lengths", [
    (0, []), (1, [1]), (999999, [999999]), (1000000, [1000000]),
    (1000001, [1000000, 1]), (2000000, [1000000, 1000000]),
    (5000001, [1000000] * 5 + [1]),
])
def test_chunk_boundaries_preserve_every_byte(size, lengths):
    from controller.objects import iter_chunks
    data = (bytes(range(256)) * (size // 256 + 1))[:size]

    async def collect():
        upload = UploadFile(BytesIO(data))
        return [chunk async for chunk in iter_chunks(upload)]

    chunks = asyncio.run(collect())
    assert [len(chunk) for chunk in chunks] == lengths
    assert b"".join(chunks) == data
