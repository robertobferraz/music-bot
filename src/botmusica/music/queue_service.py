from __future__ import annotations

from botmusica.music.player import GuildPlayer, Track


class QueueService:
    async def enqueue(self, player: GuildPlayer, track: Track) -> None:
        await player.enqueue(track)

    async def enqueue_many(self, player: GuildPlayer, tracks: list[Track]) -> int:
        for track in tracks:
            await player.enqueue(track)
        return len(tracks)

    def enqueue_front(self, player: GuildPlayer, track: Track) -> None:
        player.enqueue_front(track)

    def enqueue_front_many(self, player: GuildPlayer, tracks: list[Track]) -> int:
        for track in reversed(tracks):
            player.enqueue_front(track)
        return len(tracks)

    def clear(self, player: GuildPlayer) -> list[Track]:
        return player.clear_queue()

    def remove(self, player: GuildPlayer, position: int) -> Track:
        return player.remove_from_queue(position)

    def move(self, player: GuildPlayer, source_pos: int, target_pos: int) -> Track:
        return player.move_in_queue(source_pos, target_pos)

    def jump(self, player: GuildPlayer, position: int) -> Track:
        return player.jump_to_front(position)

    def shuffle(self, player: GuildPlayer) -> int:
        return player.shuffle_queue()
