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

