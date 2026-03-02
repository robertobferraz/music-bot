from __future__ import annotations

import math
import re
from typing import Callable
from urllib.parse import parse_qs, urlparse

import discord

from botmusica.music.player import GuildPlayer, Track

THEME_COLORS: dict[str, discord.Color] = {
    "brand": discord.Color.from_rgb(28, 170, 221),
    "general": discord.Color.from_rgb(66, 135, 245),
    "playback": discord.Color.from_rgb(16, 185, 129),
    "queue": discord.Color.from_rgb(245, 158, 11),
    "admin": discord.Color.from_rgb(239, 68, 68),
    "ok": discord.Color.from_rgb(34, 197, 94),
    "warn": discord.Color.from_rgb(249, 115, 22),
    "error": discord.Color.from_rgb(239, 68, 68),
    "metrics": discord.Color.from_rgb(14, 165, 233),
    "diagnostics": discord.Color.from_rgb(20, 184, 166),
}

# Opcional: coloque um banner fixo (ex.: um PNG do seu bot) para identidade visual.
# Se ficar None, não adiciona imagem.
EMBED_BANNER_URL: str | None = None

# Tamanho padrão da barra de progresso (visual no Now Playing)
PROGRESS_BAR_LENGTH: int = 18

HELP_CATEGORIES: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "geral": (
        "Comandos gerais para comecar a usar o bot.",
        [
            ("/help", "Abre este painel interativo de ajuda."),
            ("/join", "Conecta o bot no seu canal de voz."),
            ("/play <link_ou_busca>", "Adiciona musica ou playlist na fila e inicia a reproducao."),
            ("/playnext <link_ou_busca>", "Adiciona musica ou playlist para tocar em seguida."),
            ("/search <consulta>", "Busca top resultados e permite escolher no menu."),
            ("/fav_add <link_ou_busca>", "Salva uma musica nos seus favoritos."),
            ("/fav_list", "Lista seus favoritos salvos."),
            ("/fav_play", "Abre menu para tocar um favorito."),
            ("/queue", "Mostra musica atual e proximas da fila."),
            ("/nowplaying", "Mostra detalhes da musica atual."),
            ("/lyrics", "Busca letra da musica atual."),
            ("/247 <ativo>", "Liga/desliga modo 24/7 (sem auto-disconnect)."),
            ("/settings", "Mostra configuracoes atuais do servidor."),
            ("/diagnostico", "Mostra diagnostico tecnico rapido do bot."),
        ],
    ),
    "reproducao": (
        "Controles diretos de reproducao de audio.",
        [
            ("/pause", "Pausa a musica atual."),
            ("/resume", "Retoma a musica pausada."),
            ("/skip", "Pula a musica atual."),
            ("/stop", "Para a musica e limpa fila pendente."),
            ("/replay", "Reinicia a musica atual do inicio."),
            ("/seek <segundos>", "Avanca para um ponto especifico da musica."),
            ("/volume <1-200>", "Ajusta o volume do player."),
            ("/filter <modo>", "Aplica filtro de audio na reproducao."),
            ("/loop <off|track|queue>", "Define repeticao da faixa/fila."),
            ("/autoplay <true|false>", "Liga/desliga recomendacoes automaticas."),
        ],
    ),
    "fila": (
        "Comandos para organizar a fila de musicas.",
        [
            ("/remove <posicao>", "Remove item especifico da fila."),
            ("/move <origem> <destino>", "Move um item para outra posicao da fila."),
            ("/jump <posicao>", "Sobe um item para tocar em seguida."),
            ("/shuffle", "Embaralha a fila pendente."),
            ("/clear", "Limpa somente os itens pendentes."),
            ("/queue_events", "Mostra eventos recentes da fila (admin)."),
            ("/playlist_save <nome>", "Salva a fila atual em uma playlist pessoal."),
            ("/playlist_load <nome>", "Carrega uma playlist pessoal para a fila."),
            ("/playlist_list", "Lista suas playlists salvas."),
            ("/playlist_delete <nome>", "Remove uma playlist pessoal."),
            ("/playlist_job", "Mostra status da importacao de playlist em background."),
            ("/playlist_job_cancel", "Cancela importacao de playlist em andamento."),
        ],
    ),
    "administracao": (
        "Administração migrando para o painel web (OAuth2 + RBAC).",
        [
            ("Painel Web", "Use o painel para moderation, cache, diagnostics e control room."),
            ("ADMIN_SLASH_ENABLED=true", "Modo deprecated (1 release)."),
            ("ADMIN_SLASH_ENABLED=false", "Desativa slash administrativos."),
        ],
    ),
}


class MusicEmbeds:
    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot

    def _bot_name(self) -> str:
        user = getattr(self.bot, "user", None)
        if user is None:
            return "Bot"
        display_name = getattr(user, "display_name", None)
        if isinstance(display_name, str) and display_name.strip():
            return display_name.strip()
        name = getattr(user, "name", None)
        if isinstance(name, str) and name.strip():
            return name.strip()
        return "Bot"

    @staticmethod
    def separator() -> str:
        # Linha curta para ficar mais "orgânico" no Discord (evita parecer bloco gigante)
        return "────────────────────────"

    @staticmethod
    def theme_color(name: str) -> discord.Color:
        return THEME_COLORS.get(name, THEME_COLORS["brand"])

    @staticmethod
    def _clamp_page(page: int, total_pages: int) -> int:
        if total_pages <= 0:
            return 0
        return max(0, min(page, total_pages - 1))

    @staticmethod
    def _ellipsis(text: str, max_len: int) -> str:
        text = (text or "").strip()
        if len(text) <= max_len:
            return text
        return text[: max(0, max_len - 1)].rstrip() + "…"

    @staticmethod
    def _pill(label: str) -> str:
        # "badge" simples, fica bonito e consistente
        return f"`{label}`"

    @staticmethod
    def _parse_clock_to_seconds(text: str) -> int | None:
        """Converte 'HH:MM:SS' ou 'MM:SS' em segundos. Retorna None se não conseguir."""
        raw = (text or "").strip()
        if not raw:
            return None
        parts = raw.split(":")
        if len(parts) not in (2, 3):
            return None
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            return None

        if len(nums) == 2:
            m, s = nums
            if m < 0 or s < 0 or s >= 60:
                return None
            return m * 60 + s

        h, m, s = nums
        if h < 0 or m < 0 or s < 0 or m >= 60 or s >= 60:
            return None
        return h * 3600 + m * 60 + s

    @staticmethod
    def _progress_bar(current_seconds: int, total_seconds: int, *, length: int = PROGRESS_BAR_LENGTH) -> str:
        if total_seconds <= 0:
            return ""
        cur = max(0, min(current_seconds, total_seconds))
        ratio = cur / total_seconds
        filled = int(ratio * length)
        filled = max(0, min(filled, length))
        # Visual: ▰ preenchido / ▱ vazio
        return "".join(["▰" * filled, "▱" * (length - filled)])

    @staticmethod
    def _progress_bar_nowplaying(current_seconds: int, total_seconds: int, *, length: int = 42) -> str:
        if total_seconds <= 0:
            return ""
        cur = max(0, min(current_seconds, total_seconds))
        ratio = cur / total_seconds
        cursor = int(ratio * (length - 1))
        cursor = max(0, min(cursor, length - 1))
        chars: list[str] = []
        for idx in range(length):
            if idx < cursor:
                chars.append("━")
            elif idx == cursor:
                chars.append("◉")
            else:
                chars.append("•")
        return "".join(chars)

    @staticmethod
    def _fmt_bool(on: bool) -> str:
        return "on" if on else "off"

    @staticmethod
    def _safe_text(text: str | None, fallback: str = "—") -> str:
        value = (text or "").strip()
        return value if value else fallback

    @staticmethod
    def _pick_np_color(loop_mode: str, autoplay_on: bool) -> discord.Color:
        _ = (loop_mode, autoplay_on)  # hook para regras visuais futuras
        return THEME_COLORS["playback"]

    @staticmethod
    def _safe_embed_url(url: str | None) -> str | None:
        raw = (url or "").strip()
        if not raw:
            return None
        try:
            parsed = urlparse(raw)
        except ValueError:
            return None
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return raw
        return None

    def _decorate(self, embed: discord.Embed) -> discord.Embed:
        """Aplica identidade visual (banner opcional) de forma consistente."""
        if EMBED_BANNER_URL:
            embed.set_image(url=EMBED_BANNER_URL)
        return embed

    def _author_icon(self) -> str | None:
        if self.bot.user and self.bot.user.display_avatar:
            return self.bot.user.display_avatar.url
        return None

    def embed(self, title: str, description: str, *, color: discord.Color) -> discord.Embed:
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        bot_name = self._bot_name()
        embed.set_author(name=bot_name, icon_url=self._author_icon())
        embed.set_footer(text=f"{bot_name} • /help para comandos")
        self._decorate(embed)
        return embed

    def ok_embed(self, title: str, description: str) -> discord.Embed:
        return self.embed(
            f"✅ {title}",
            f"{description}",
            color=self.theme_color("ok"),
        )

    def warn_embed(self, title: str, description: str) -> discord.Embed:
        return self.embed(
            f"⚠️ {title}",
            f"{description}",
            color=self.theme_color("warn"),
        )

    def error_embed(self, title: str, description: str) -> discord.Embed:
        return self.embed(
            f"❌ {title}",
            f"{description}",
            color=self.theme_color("error"),
        )

    def build_help_embed(self, category: str) -> discord.Embed:
        description, commands_list = HELP_CATEGORIES.get(category, HELP_CATEGORIES["geral"])

        title_map = {
            "geral": "📘 Ajuda",
            "reproducao": "🎚️ Reprodução",
            "fila": "📜 Fila",
            "administracao": "🛡️ Administração",
        }
        color_map = {
            "geral": "general",
            "reproducao": "playback",
            "fila": "queue",
            "administracao": "admin",
        }

        embed = self.embed(
            title_map.get(category, "📘 Ajuda"),
            (
                f"Bem-vindo ao **{self._bot_name()}** 🎧\n"
                "Selecione uma categoria no menu (ou digite `/` no chat).\n"
                f"{self.separator()}\n"
                f"{description}"
            ),
            color=self.theme_color(color_map.get(category, "brand")),
        )

        embed.add_field(
            name="🧭 Categorias",
            value=(
                f"• {self._pill('geral')} Comandos base\n"
                f"• {self._pill('reproducao')} Controles\n"
                f"• {self._pill('fila')} Organização\n"
                f"• {self._pill('administracao')} Configurações"
            ),
            inline=False,
        )

        max_cmds = 12
        lines = [f"• `{name}` — {desc}" for name, desc in commands_list[:max_cmds]]
        if len(commands_list) > max_cmds:
            lines.append(f"• … e mais {len(commands_list) - max_cmds} comandos")

        embed.add_field(
            name="📌 Comandos",
            value="\n".join(lines) if lines else "Nenhum comando listado.",
            inline=False,
        )

        embed.set_footer(text="Dica: digite `/` no chat e use o autocomplete do Discord")
        return embed

    def build_queue_embed(
        self,
        *,
        player: GuildPlayer,
        items: list[Track],
        page: int,
        format_duration: Callable[[int | None], str],
    ) -> discord.Embed:
        # Tocando agora
        if player.current:
            current_title = self._ellipsis(player.current.title, 64)
            current_artist = self._ellipsis((player.current.artist or "").strip(), 40)
            artist_line = f"\n👤 {self._pill(current_artist)}" if current_artist else ""
            current = (
                f"**{current_title}**\n"
                f"{self._pill(format_duration(player.current.duration_seconds))} "
                f"• pedido por {self._pill(str(player.current.requested_by))}"
                f"{artist_line}"
            )
        else:
            current = "Nada tocando no momento."

        loop_badge = self._pill(f"loop: {player.loop_mode}")
        autoplay_badge = self._pill("autoplay: on" if player.autoplay else "autoplay: off")
        filter_badge = self._pill(f"filtro: {player.audio_filter}")

        embed = self.embed(
            "📜 Fila do DJ",
            "Visão rápida do player e próximas faixas.",
            color=self.theme_color("queue"),
        )

        embed.add_field(name="🎧 Tocando agora", value=current, inline=False)
        embed.add_field(name="⚙️ Estado", value=f"{loop_badge}  {autoplay_badge}  {filter_badge}", inline=False)

        # Se fila vazia
        if not items:
            embed.add_field(name="📭 Próximas", value="Fila vazia.", inline=False)
            embed.set_footer(text="Página 1/1")
            return embed

        per_page = 10
        total_pages = max(math.ceil(len(items) / per_page), 1)
        safe_page = self._clamp_page(page, total_pages)
        start = safe_page * per_page
        chunk = items[start : start + per_page]

        # Listagem mais legível: índice global + título truncado + duração + requester
        preview_lines: list[str] = []
        for idx, track in enumerate(chunk, start=1):
            global_pos = start + idx
            title = self._ellipsis(track.title, 48)
            artist = self._ellipsis((track.artist or "").strip(), 28)
            dur = format_duration(track.duration_seconds)
            req = self._ellipsis(str(track.requested_by), 24)
            artist_part = f" • 👤 {artist}" if artist else ""
            preview_lines.append(f"`{global_pos:02d}` **{title}** • {self._pill(dur)} • {req}{artist_part}")

        embed.add_field(name="▶️ Próximas", value="\n".join(preview_lines), inline=False)
        embed.set_footer(text=f"Página {safe_page + 1}/{total_pages} • Total na fila: {len(items)}")
        return embed

    def build_nowplaying_embed(
        self,
        *,
        track: Track,
        progress_value: str,
        duration_text: str,
        audio_filter: str,
        requested_by: str,
        source_url: str,
        volume_percent: int,
        loop_mode: str,
        autoplay_on: bool,
        compact_mode: bool = False,
    ) -> discord.Embed:
        title = self._ellipsis(track.title, 88)
        artist = self._safe_text(self._ellipsis((track.artist or "").strip(), 60), "Artista desconhecido")
        requested_by = self._safe_text(requested_by, "—")
        audio_filter = self._safe_text(audio_filter, "off")
        loop_mode = self._safe_text(loop_mode, "off")
        progress_display = self._safe_text(progress_value, "—")

        bar_line = ""
        clocks_line = ""
        clock_match = re.search(r"(\d{1,2}:\d{2}(?::\d{2})?)\s*/\s*(\d{1,2}:\d{2}(?::\d{2})?)", progress_display)
        if clock_match:
            left = clock_match.group(1).strip()
            right = clock_match.group(2).strip()
            cur_s = self._parse_clock_to_seconds(left)
            tot_s = self._parse_clock_to_seconds(right)
            if cur_s is not None and tot_s is not None and tot_s > 0:
                bar = self._progress_bar_nowplaying(cur_s, tot_s)
                if bar:
                    clocks_line = f"`{left} / {right}`"
                    bar_line = f"`{bar}`"
                else:
                    clocks_line = f"`{left} / {right}`"
            else:
                clocks_line = f"`{left} / {right}`"
        elif "ao vivo" in progress_display.casefold():
            clocks_line = "`ao vivo`"
        else:
            cleaned = progress_display.replace("`", "").replace("\n", " ").strip()
            clocks_line = f"`{self._safe_text(cleaned)}`"

        color = self._pick_np_color(loop_mode, autoplay_on)
        embed = discord.Embed(
            title=title,
            description=f"**{artist}**",
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        safe_url = self._safe_embed_url(source_url)
        if safe_url:
            embed.url = safe_url

        bot_name = self._bot_name()
        embed.set_author(
            name=f"{bot_name}  •  🟢 Agora tocando",
            icon_url=self._author_icon() or None,
        )

        thumb = self._youtube_thumbnail_url(safe_url or "") if safe_url else None
        if thumb:
            embed.set_thumbnail(url=thumb)
        if clocks_line and bar_line:
            embed.add_field(name="⏱️ Progresso", value=f"{clocks_line}\n{bar_line}", inline=False)
        else:
            embed.add_field(name="⏱️ Progresso", value=clocks_line or "`—`", inline=False)

        if compact_mode:
            embed.add_field(
                name="⚙️ Status",
                value=(
                    f"🔊 {self._pill(f'{volume_percent}%')}  "
                    f"🎛️ {self._pill(audio_filter)}  "
                    f"🔁 {self._pill(loop_mode)}  "
                    f"🤖 {self._pill(self._fmt_bool(autoplay_on))}"
                ),
                inline=False,
            )
            if safe_url:
                embed.add_field(name="🔗 Fonte", value=f"[Abrir link]({safe_url})", inline=False)
            embed.set_footer(text=f"{bot_name} • {self._ellipsis(title, 42)} • Compact • /help")
            self._decorate(embed)
            return embed

        embed.add_field(name="🟡 Duração", value=self._pill(duration_text), inline=True)
        embed.add_field(name="🙋 Pedido", value=self._pill(requested_by), inline=True)
        embed.add_field(name="🔊 Volume", value=f"**{volume_percent}%**", inline=True)
        status = (
            f"🎛️ filtro: {self._pill(audio_filter)}  •  "
            f"🔁 loop: {self._pill(loop_mode)}  •  "
            f"🤖 autoplay: {self._pill(self._fmt_bool(autoplay_on))}"
        )
        embed.add_field(name="⚙️ Configuração", value=status, inline=False)
        if safe_url:
            embed.add_field(name="🔗 Fonte", value=f"[Abrir link]({safe_url})", inline=False)
        embed.set_footer(text=f"{bot_name} • Painel do player • /help")
        self._decorate(embed)
        return embed

    @staticmethod
    def _youtube_thumbnail_url(url: str) -> str | None:
        try:
            parsed = urlparse(url)
        except ValueError:
            return None
        host = (parsed.hostname or "").casefold()
        if host in {"youtu.be"}:
            video_id = parsed.path.strip("/")
            if video_id:
                return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
            return None
        if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
            return None
        video_id = parse_qs(parsed.query).get("v", [""])[0].strip()
        if not video_id:
            return None
        return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
