"""
Voice Bot Configuration Settings
Загрузка конфигурации из YAML и переменных окружения
"""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class VoiceTTSConfig(BaseModel):
    """TTS (Text-to-Speech) настройки"""
    voice: str = "алена"
    emotion: str = "good"
    speed: float = 1.0
    volume: float = 1.0
    format: str = "lpcm"
    sample_rate: int = 8000


class VoiceASRConfig(BaseModel):
    """ASR (Automatic Speech Recognition) настройки"""
    language: str = "ru-RU"
    model: str = "general"
    audio_format: str = "lpcm"
    sample_rate: int = 8000
    partial_results: bool = True
    speech_timeout: int = 10
    silence_threshold: float = 1.0


class VoiceConfig(BaseModel):
    """Настройки голоса"""
    tts: VoiceTTSConfig = Field(default_factory=VoiceTTSConfig)
    asr: VoiceASRConfig = Field(default_factory=VoiceASRConfig)


class LLMConfig(BaseModel):
    """LLM настройки"""
    model: str = "gpt-4o"
    max_tokens: int = 150
    temperature: float = 0.7
    system_prompt: str = "Ты — голосовой помощник."


class DialogConfig(BaseModel):
    """Настройки диалога"""
    greeting: str = "Добрый день! Чем могу помочь?"
    waiting: str = "Одну секунду..."
    not_understood: str = "Извините, не расслышала. Повторите, пожалуйста."
    goodbye: str = "Спасибо за звонок! Хорошего дня!"
    max_duration: int = 300
    max_turns: int = 50


class FreeSWITCHConfig(BaseModel):
    """FreeSWITCH ESL настройки"""
    host: str = "127.0.0.1"
    port: int = 8021
    password: str = "ClueCon"
    timeout: int = 30


class LoggingConfig(BaseModel):
    """Настройки логирования"""
    level: str = "INFO"
    file: str = "/var/log/voice-bot/bot.log"
    max_size: int = 10
    backup_count: int = 5


class AgentConfig(BaseModel):
    """Конфигурация агента"""
    name: str = "Voice Bot"
    version: str = "1.0.0"


class Settings(BaseSettings):
    """Главные настройки приложения"""

    # API ключи из переменных окружения
    yandex_api_key: Optional[str] = None
    yandex_folder_id: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_api_base: str = "https://api.openai.com/v1"

    # Конфигурация из YAML
    agent: AgentConfig = Field(default_factory=AgentConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    dialog: DialogConfig = Field(default_factory=DialogConfig)
    freeswitch: FreeSWITCHConfig = Field(default_factory=FreeSWITCHConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


def load_config(config_path: Optional[str] = None) -> Settings:
    """
    Загрузка конфигурации из YAML файла и переменных окружения

    Args:
        config_path: Путь к YAML файлу конфигурации

    Returns:
        Settings: Объект с настройками
    """
    # Путь к конфигу по умолчанию
    if config_path is None:
        config_path = os.environ.get(
            "VOICE_BOT_CONFIG",
            str(Path(__file__).parent / "agent.yaml")
        )

    # Загрузка YAML
    yaml_data = {}
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}

    # Создание настроек
    settings = Settings()

    # Применение данных из YAML
    if "agent" in yaml_data:
        settings.agent = AgentConfig(**yaml_data["agent"])
    if "voice" in yaml_data:
        settings.voice = VoiceConfig(**yaml_data["voice"])
    if "llm" in yaml_data:
        settings.llm = LLMConfig(**yaml_data["llm"])
    if "dialog" in yaml_data:
        settings.dialog = DialogConfig(**yaml_data["dialog"])
    if "freeswitch" in yaml_data:
        settings.freeswitch = FreeSWITCHConfig(**yaml_data["freeswitch"])
    if "logging" in yaml_data:
        settings.logging = LoggingConfig(**yaml_data["logging"])

    return settings


# Глобальный объект настроек
settings = load_config()
