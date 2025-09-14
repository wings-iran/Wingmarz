from aiogram import Bot
from typing import Any, Optional

from .text_utils import convert_markdown_bold_to_html


class BoldFixBot(Bot):
    async def send_message(self, chat_id: int | str, text: str, *args: Any, **kwargs: Any):
        if isinstance(text, str):
            text = convert_markdown_bold_to_html(text)
        return await super().send_message(chat_id, text, *args, **kwargs)

    async def edit_message_text(
        self,
        text: str,
        chat_id: Optional[int | str] = None,
        message_id: Optional[int] = None,
        inline_message_id: Optional[str] = None,
        *args: Any,
        **kwargs: Any,
    ):
        if isinstance(text, str):
            text = convert_markdown_bold_to_html(text)
        return await super().edit_message_text(text, chat_id, message_id, inline_message_id, *args, **kwargs)

    async def send_photo(self, chat_id: int | str, photo: Any, *args: Any, **kwargs: Any):
        caption = kwargs.get("caption")
        if isinstance(caption, str):
            kwargs["caption"] = convert_markdown_bold_to_html(caption)
        return await super().send_photo(chat_id, photo, *args, **kwargs)

    async def edit_message_caption(
        self,
        chat_id: Optional[int | str] = None,
        message_id: Optional[int] = None,
        inline_message_id: Optional[str] = None,
        caption: Optional[str] = None,
        *args: Any,
        **kwargs: Any,
    ):
        if isinstance(caption, str):
            caption = convert_markdown_bold_to_html(caption)
        return await super().edit_message_caption(chat_id, message_id, inline_message_id, caption, *args, **kwargs)

    async def send_document(self, chat_id: int | str, document: Any, *args: Any, **kwargs: Any):
        caption = kwargs.get("caption")
        if isinstance(caption, str):
            kwargs["caption"] = convert_markdown_bold_to_html(caption)
        return await super().send_document(chat_id, document, *args, **kwargs)

    async def send_audio(self, chat_id: int | str, audio: Any, *args: Any, **kwargs: Any):
        caption = kwargs.get("caption")
        if isinstance(caption, str):
            kwargs["caption"] = convert_markdown_bold_to_html(caption)
        return await super().send_audio(chat_id, audio, *args, **kwargs)

    async def send_video(self, chat_id: int | str, video: Any, *args: Any, **kwargs: Any):
        caption = kwargs.get("caption")
        if isinstance(caption, str):
            kwargs["caption"] = convert_markdown_bold_to_html(caption)
        return await super().send_video(chat_id, video, *args, **kwargs)

    async def send_animation(self, chat_id: int | str, animation: Any, *args: Any, **kwargs: Any):
        caption = kwargs.get("caption")
        if isinstance(caption, str):
            kwargs["caption"] = convert_markdown_bold_to_html(caption)
        return await super().send_animation(chat_id, animation, *args, **kwargs)

    async def send_voice(self, chat_id: int | str, voice: Any, *args: Any, **kwargs: Any):
        caption = kwargs.get("caption")
        if isinstance(caption, str):
            kwargs["caption"] = convert_markdown_bold_to_html(caption)
        return await super().send_voice(chat_id, voice, *args, **kwargs)

    async def send_media_group(self, chat_id: int | str, media: Any, *args: Any, **kwargs: Any):
        try:
            # media is a list of InputMedia* with optional .caption
            for item in media or []:
                cap = getattr(item, "caption", None)
                if isinstance(cap, str):
                    setattr(item, "caption", convert_markdown_bold_to_html(cap))
        except Exception:
            pass
        return await super().send_media_group(chat_id, media, *args, **kwargs)

    async def edit_message_media(
        self,
        media: Any,
        chat_id: Optional[int | str] = None,
        message_id: Optional[int] = None,
        inline_message_id: Optional[str] = None,
        *args: Any,
        **kwargs: Any,
    ):
        try:
            cap = getattr(media, "caption", None)
            if isinstance(cap, str):
                setattr(media, "caption", convert_markdown_bold_to_html(cap))
        except Exception:
            pass
        return await super().edit_message_media(media, chat_id, message_id, inline_message_id, *args, **kwargs)

    async def __call__(self, method, *args: Any, **kwargs: Any):
        """
        Intercept all API method calls to ensure Markdown-like bold/italic/code
        are converted to Telegram-safe HTML even when using Message.* helpers
        that invoke the Bot via __call__ with a Method object.
        Only converts when the payload appears to contain markdown markers to
        avoid re-escaping already-HTML texts.
        """
        try:
            text = getattr(method, "text", None)
            if isinstance(text, str) and any(marker in text for marker in ("**", "__", "`", "*", "_")):
                setattr(method, "text", convert_markdown_bold_to_html(text))
        except Exception:
            pass
        try:
            caption = getattr(method, "caption", None)
            if isinstance(caption, str) and any(marker in caption for marker in ("**", "__", "`", "*", "_")):
                setattr(method, "caption", convert_markdown_bold_to_html(caption))
        except Exception:
            pass
        return await super().__call__(method, *args, **kwargs)

