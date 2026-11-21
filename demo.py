"""Render every template without Telegram or API keys.

    python demo.py [poster.jpg] [backdrop.jpg] [extra.jpg ...]     ->  ./out/<template>.png
"""
import sys
import time
from pathlib import Path

from bot import templates
from bot.context import Ctx
from bot.models import Media


def main() -> None:
    imgs = sys.argv[1:]
    media = Media(
        source="demo", kind="anime", id=0, title="Alya Sometimes Hides Her Feelings in Russian",
        year="2024", episodes="12", unit="Episodes", genres=["Comedy", "Romance", "Slice of Life"],
        synopsis=("Alya is a transfer student enjoying popularity at her new high school, often sporting a cold "
                  "shoulder while earning high marks in class. She ignores her nerdy classmate, Kuze, but secretly "
                  "whispers sweet words in Russian."),
        poster=imgs[0] if imgs else "", backdrop=imgs[1] if len(imgs) > 1 else "", extras=imgs[2:],
        studio="Doga Kobo", status="Returning Series", type_label="TV SERIES", score="8.1",
    )
    out = Path("out")
    out.mkdir(exist_ok=True)
    for key, tpl in templates.TEMPLATES.items():
        t = time.time()
        (out / f"{key}.png").write_bytes(templates.render(key, Ctx(media, brand="AniCruise", accent=tpl.accent), 1).png())
        print(f"{key:14s} {time.time() - t:.2f}s")


if __name__ == "__main__":
    main()
