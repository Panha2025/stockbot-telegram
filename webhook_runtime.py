"""PostgreSQL persistence used by stateless Telegram webhook invocations."""

from decimal import Decimal
import json

from telegram.ext import BasePersistence


_DECIMAL_MARKER = "__stockbot_decimal__"


def _json_default(value):
    if isinstance(value, Decimal):
        return {_DECIMAL_MARKER: str(value)}
    raise TypeError(f"Unsupported persistence value: {type(value).__name__}")


def _object_hook(value):
    if set(value) == {_DECIMAL_MARKER}:
        return Decimal(value[_DECIMAL_MARKER])
    return value


def _decode(value):
    if isinstance(value, str):
        return json.loads(value, object_hook=_object_hook)
    if value is None:
        return {}
    # psycopg normally decodes jsonb itself. Round-trip so Decimal markers use
    # the same decoding path with both psycopg and lightweight test doubles.
    return json.loads(json.dumps(value, default=_json_default), object_hook=_object_hook)


def _encode(value):
    return json.dumps(value, default=_json_default, separators=(",", ":"))


class PostgresBotPersistence(BasePersistence):
    """Persist one private Telegram account's PTB state in ``shop_users``."""

    def __init__(self, store, user_id):
        super().__init__(update_interval=1)
        self.store = store
        self.user_id = int(user_id)

    def _read(self, column):
        if column not in {"bot_user_data", "bot_conversations"}:
            raise ValueError("Unsupported persistence column")
        with self.store._connection(self.user_id) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {column} FROM public.shop_users WHERE telegram_user_id = %s",
                (self.user_id,),
            )
            row = cur.fetchone()
        return _decode(row[0]) if row else {}

    def _write_user_data(self, data):
        with self.store._connection(self.user_id) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE public.shop_users SET bot_user_data = %s::jsonb "
                "WHERE telegram_user_id = %s",
                (_encode(data), self.user_id),
            )

    async def get_user_data(self):
        data = self._read("bot_user_data")
        return {self.user_id: data} if data else {}

    async def update_user_data(self, user_id, data):
        if int(user_id) == self.user_id:
            self._write_user_data(data)

    async def refresh_user_data(self, user_id, user_data):
        return None

    async def drop_user_data(self, user_id):
        if int(user_id) == self.user_id:
            self._write_user_data({})

    async def get_chat_data(self):
        return {self.user_id: {}}

    async def update_chat_data(self, chat_id, data):
        return None

    async def refresh_chat_data(self, chat_id, chat_data):
        return None

    async def drop_chat_data(self, chat_id):
        return None

    async def get_bot_data(self):
        return {}

    async def update_bot_data(self, data):
        return None

    async def refresh_bot_data(self, bot_data):
        return None

    async def get_callback_data(self):
        return None

    async def update_callback_data(self, data):
        return None

    async def get_conversations(self, name):
        conversations = self._read("bot_conversations").get(name, {})
        return {tuple(json.loads(key)): state for key, state in conversations.items()}

    async def update_conversation(self, name, key, new_state):
        # A PTB persistence object is instantiated for one verified private
        # account only. Refuse keys belonging to any other account.
        if not isinstance(key, tuple) or len(key) < 2 or key[0] != self.user_id or key[1] != self.user_id:
            return
        encoded_key = json.dumps(list(key), separators=(",", ":"))
        with self.store._connection(self.user_id) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT bot_conversations FROM public.shop_users "
                "WHERE telegram_user_id = %s FOR UPDATE",
                (self.user_id,),
            )
            row = cur.fetchone()
            if row is None:
                return
            conversations = _decode(row[0])
            named = conversations.setdefault(name, {})
            if new_state is None:
                named.pop(encoded_key, None)
            else:
                named[encoded_key] = new_state
            if not named:
                conversations.pop(name, None)
            cur.execute(
                "UPDATE public.shop_users SET bot_conversations = %s::jsonb "
                "WHERE telegram_user_id = %s",
                (_encode(conversations), self.user_id),
            )

    async def flush(self):
        return None
