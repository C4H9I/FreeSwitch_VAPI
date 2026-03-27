"""
LLM Integration
Интеграция с OpenAI-совместимым API для генерации ответов

Поддерживает:
- OpenAI GPT-4, GPT-4o, GPT-3.5
- Совместимые API (Azure OpenAI, LocalAI, Ollama, vLLM)
"""

import asyncio
from typing import Optional, List, Dict, AsyncGenerator
from dataclasses import dataclass, field

from loguru import logger
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam


@dataclass
class Message:
    """Сообщение в диалоге"""
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class ConversationContext:
    """Контекст диалога"""
    system_prompt: str
    messages: List[Message] = field(default_factory=list)
    max_messages: int = 20  # Максимальное количество сообщений в истории

    def add_message(self, role: str, content: str) -> None:
        """Добавление сообщения в историю"""
        self.messages.append(Message(role=role, content=content))

        # Ограничение истории
        if len(self.messages) > self.max_messages:
            # Оставляем последнее сообщение и часть истории
            self.messages = self.messages[-self.max_messages:]

    def clear(self) -> None:
        """Очистка истории"""
        self.messages = []

    def get_messages(self) -> List[ChatCompletionMessageParam]:
        """Получение сообщений в формате OpenAI"""
        result: List[ChatCompletionMessageParam] = [
            {"role": "system", "content": self.system_prompt}
        ]
        for msg in self.messages:
            result.append({"role": msg.role, "content": msg.content})
        return result


class LLMClient:
    """
    Клиент для работы с LLM API

    Поддерживает:
    - Синхронный и потоковый вывод
    - Управление контекстом диалога
    - Обработку ошибок и повторные попытки
    """

    def __init__(
        self,
        api_key: str,
        api_base: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        max_tokens: int = 150,
        temperature: float = 0.7,
        system_prompt: str = "Ты — голосовой помощник.",
    ):
        """
        Инициализация LLM клиента

        Args:
            api_key: API ключ
            api_base: URL API endpoint
            model: Имя модели
            max_tokens: Максимальное количество токенов в ответе
            temperature: Температура генерации (0.0 - 2.0)
            system_prompt: Системный промпт
        """
        self.api_key = api_key
        self.api_base = api_base
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.system_prompt = system_prompt

        # OpenAI клиент
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
        )

        # Контекст диалога (по одному на каждого пользователя/звонок)
        self._contexts: Dict[str, ConversationContext] = {}

    def get_context(self, session_id: str) -> ConversationContext:
        """
        Получение или создание контекста для сессии

        Args:
            session_id: ID сессии/звонка

        Returns:
            ConversationContext: Контекст диалога
        """
        if session_id not in self._contexts:
            self._contexts[session_id] = ConversationContext(
                system_prompt=self.system_prompt
            )
        return self._contexts[session_id]

    def clear_context(self, session_id: str) -> None:
        """Очистка контекста сессии"""
        if session_id in self._contexts:
            del self._contexts[session_id]

    async def generate(
        self,
        user_message: str,
        session_id: str,
    ) -> str:
        """
        Генерация ответа на сообщение пользователя

        Args:
            user_message: Сообщение пользователя
            session_id: ID сессии

        Returns:
            str: Ответ ассистента
        """
        context = self.get_context(session_id)

        # Добавление сообщения пользователя
        context.add_message("user", user_message)

        try:
            # Запрос к LLM
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=context.get_messages(),
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            # Извлечение ответа
            assistant_message = response.choices[0].message.content or ""

            # Добавление ответа в контекст
            context.add_message("assistant", assistant_message)

            logger.debug(f"LLM response: {assistant_message[:100]}...")
            return assistant_message

        except Exception as e:
            logger.error(f"LLM API error: {e}")
            # Удаление последнего сообщения пользователя при ошибке
            if context.messages:
                context.messages.pop()
            raise

    async def generate_stream(
        self,
        user_message: str,
        session_id: str,
    ) -> AsyncGenerator[str, None]:
        """
        Потоковая генерация ответа

        Args:
            user_message: Сообщение пользователя
            session_id: ID сессии

        Yields:
            str: Части ответа
        """
        context = self.get_context(session_id)
        context.add_message("user", user_message)

        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=context.get_messages(),
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=True,
            )

            full_response = ""
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    full_response += text
                    yield text

            # Сохранение полного ответа в контекст
            context.add_message("assistant", full_response)

        except Exception as e:
            logger.error(f"LLM API streaming error: {e}")
            if context.messages:
                context.messages.pop()
            raise

    async def generate_with_prompt(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        Генерация ответа с кастомным системным промптом

        Args:
            user_message: Сообщение пользователя
            system_prompt: Кастомный системный промпт
            session_id: ID сессии (опционально)

        Returns:
            str: Ответ ассистента
        """
        messages: List[ChatCompletionMessageParam] = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        else:
            messages.append({"role": "system", "content": self.system_prompt})

        messages.append({"role": "user", "content": user_message})

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )

            return response.choices[0].message.content or ""

        except Exception as e:
            logger.error(f"LLM API error: {e}")
            raise

    async def close(self) -> None:
        """Закрытие клиента"""
        await self._client.close()


class MockLLM:
    """
    Mock LLM для тестирования без реального API
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.system_prompt = kwargs.get("system_prompt", "Ты — голосовой помощник.")
        logger.info("MockLLM initialized for testing")

    def get_context(self, session_id: str) -> ConversationContext:
        return ConversationContext(system_prompt=self.system_prompt)

    def clear_context(self, session_id: str) -> None:
        pass

    async def generate(self, user_message: str, session_id: str) -> str:
        """Mock генерация - возвращает заглушку"""
        return "Это тестовый ответ голосового помощника. Я понял ваше сообщение."

    async def generate_stream(
        self,
        user_message: str,
        session_id: str,
    ) -> AsyncGenerator[str, None]:
        """Mock потоковая генерация"""
        response = "Это тестовый ответ голосового помощника."
        for word in response.split():
            yield word + " "
            await asyncio.sleep(0.05)

    async def generate_with_prompt(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        return await self.generate(user_message, session_id or "mock")

    async def close(self) -> None:
        pass


def create_llm(
    api_key: str,
    api_base: str = "https://api.openai.com/v1",
    use_mock: bool = False,
    **kwargs
) -> LLMClient | MockLLM:
    """
    Фабрика для создания LLM клиента

    Args:
        api_key: API ключ
        api_base: URL API endpoint
        use_mock: Использовать mock для тестирования
        **kwargs: Дополнительные параметры

    Returns:
        LLM клиент
    """
    if use_mock or not api_key:
        logger.warning("Using Mock LLM - no real generation will be performed")
        return MockLLM(api_key=api_key, api_base=api_base, **kwargs)

    return LLMClient(
        api_key=api_key,
        api_base=api_base,
        **kwargs
    )
