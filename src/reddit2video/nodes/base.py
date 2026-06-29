from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from reddit2video.models import NodeSpec
from reddit2video.errors import NodeError


InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class BaseNode(ABC, Generic[InputT, OutputT]):
    spec: NodeSpec

    def __call__(self, node_input: InputT) -> OutputT:
        return self.run(node_input)

    @abstractmethod
    def run(self, node_input: InputT) -> OutputT:
        raise NotImplementedError


class AsyncBaseNode(ABC, Generic[InputT, OutputT]):
    spec: NodeSpec

    async def __call__(self, node_input: InputT) -> OutputT:
        return await self.run(node_input)

    @abstractmethod
    async def run(self, node_input: InputT) -> OutputT:
        raise NotImplementedError
