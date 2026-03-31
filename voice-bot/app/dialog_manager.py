"""Dialog Manager"""

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from loguru import logger

from .asr import create_asr
from .tts import create_tts
from .llm import create_llm


class DialogState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    ENDED = "ended"


@dataclass
class DialogTurn:
    user_text: Optional[str] = None
    assistant_text: Optional[str] = None


class DialogManager:
    def __init__(self, asr, tts, llm, greeting="Добрый день!", goodbye="До свидания!", 
                 not_understood="Не расслышала.", max_turns=50):
        self.asr = asr
        self.tts = tts
        self.llm = llm
        self.greeting = greeting
        self.goodbye = goodbye
        self.not_understood = not_understood
        self.max_turns = max_turns
        self.state = DialogState.IDLE
        self.turn_count = 0
        self.session_id = None
        self.start_time = None

    async def start_session(self, session_id: str):
        self.session_id = session_id
        self.state = DialogState.SPEAKING
        self.start_time = time.time()
        self.turn_count = 0
        logger.info(f"Dialog started: {session_id}")
        return await self.tts.synthesize(self.greeting)

    async def process_text(self, text: str):
        if not self.session_id:
            self.session_id = "default"
        
        if self._is_goodbye(text):
            return await self._end_dialog()
        
        response_text = await self.llm.generate(text, self.session_id)
        self.turn_count += 1
        logger.info(f"Turn {self.turn_count}: {text[:30]}... -> {response_text[:30]}...")
        
        return await self.tts.synthesize(response_text)

    async def _end_dialog(self):
        self.state = DialogState.ENDED
        logger.info(f"Dialog ended: {self.session_id} (turns: {self.turn_count})")
        return await self.tts.synthesize(self.goodbye)

    def _is_goodbye(self, text: str) -> bool:
        phrases = ["до свидания", "пока", "прощай", "bye", "goodbye", "стоп"]
        return any(p in text.lower() for p in phrases)

    def get_stats(self):
        return {"session": self.session_id, "turns": self.turn_count, "state": self.state.value}


def create_dialog_manager(
    yandex_api_key: str = "",
    yandex_folder_id: Optional[str] = None,
    openai_api_key: str = "",
    openai_api_base: str = "https://api.openai.com/v1",
    system_prompt: str = "Ты помощник.",
    voice_config: dict = None,
    dialog_config: dict = None,
    use_mock_asr_tts: bool = False,
    use_mock_llm: bool = False,
):
    voice_config = voice_config or {}
    dialog_config = dialog_config or {}
    
    # ASR
    asr = create_asr(
        api_key=yandex_api_key,
        folder_id=yandex_folder_id,
        use_mock=(use_mock_asr_tts or not yandex_api_key),
    )
    
    # TTS
    tts = create_tts(
        api_key=yandex_api_key,
        folder_id=yandex_folder_id,
        use_mock=(use_mock_asr_tts or not yandex_api_key),
        voice=voice_config.get("tts", {}).get("voice", "алена"),
    )
    
    # LLM
    llm = create_llm(
        api_key=openai_api_key,
        api_base=openai_api_base,
        use_mock=(use_mock_llm or not openai_api_key),
        model=dialog_config.get("llm_model", "gpt-4o-mini"),
        max_tokens=dialog_config.get("max_tokens", 150),
        system_prompt=system_prompt,
    )
    
    return DialogManager(
        asr=asr, tts=tts, llm=llm,
        greeting=dialog_config.get("greeting", "Добрый день!"),
        goodbye=dialog_config.get("goodbye", "До свидания!"),
        not_understood=dialog_config.get("not_understood", "Не расслышала."),
        max_turns=dialog_config.get("max_turns", 50),
    )
