#!/usr/bin/env python3
"""Генерация изображений сайта через Higgsfield Nano Banana Pro.

Использование:
    python3 design/gen.py            # все задания из JOBS, которых ещё нет
    python3 design/gen.py hero-desktop og   # только указанные
Результаты: design/generated/<name>.png, промпты сохраняются в design/prompts.json.
"""
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "generated"
REFS = ROOT / "refs"

PHOTO = (
    " Photorealistic documentary photograph, full-frame camera, natural colors, "
    "blue hour: deep navy-blue sky, warm golden-yellow street-light glow, subtle reflections on damp asphalt. "
    "No readable text, no signs with letters, no logos, no watermark."
)
GPT = dict(model="gpt_image_2_5", quality="xhigh", background="transparent")
CUTOUT = " Isolated on a fully transparent background, no backdrop, no frame, no ground shadow outside the scene."
FLAT = (
    " Flat vector illustration, minimal geometric shapes, clean edges, no outlines, no gradients except soft light cones, "
    "strict limited palette: deep navy #14213D, twilight blue #3D5A80, slate #5B6475, warm sodium yellow #FFB81C for lamps and light, "
    "off-white #F4F7FB highlights. Calm night mood. No text, no letters, no numbers."
)

JOBS = {
    "hero-desktop": dict(ar="16:9", res="4k", prompt=(
        "Wide cinematic photograph of a quiet street in the Russian regional city of Kirov at blue hour, minutes after the street lights "
        "switched on. On the right side a long row of modern LED street lamps on slim grey poles recedes into perspective, each casting "
        "a warm yellow cone of light onto the damp asphalt and sidewalk. Typical Kirov architecture: old two-storey red-brick merchant houses "
        "and Soviet five-storey apartment blocks with a few warm lit windows, bare birch trees, autumn. The left 45 percent of the frame is "
        "darker and calm (deep navy sky and shadowed road) leaving clean negative space for a headline. Eye level, 35mm lens, gentle haze, "
        "no people, no cars in the foreground." + PHOTO)),
    "hero-mobile": dict(ar="3:4", res="2k", prompt=(
        "Vertical photograph of a quiet residential street in the Russian city of Kirov at blue hour: a row of modern LED street lamps on slim "
        "poles runs along the right sidewalk towards a vanishing point, warm yellow light cones on damp asphalt, Soviet five-storey apartment "
        "blocks and bare birches. The upper 40 percent of the frame is clean dark navy sky, empty, for a headline. No people." + PHOTO)),
    "owner-street": dict(ar="4:3", res="2k", **GPT, prompt=(
        "Spot illustration: a short piece of city street seen slightly from above: a road with a zebra crossing, tall street lamps with long "
        "arms on both sides of the carriageway casting yellow trapezoid light cones onto the road, a small car silhouette, two low apartment "
        "buildings behind. The scene is a compact rounded vignette." + FLAT + CUTOUT)),
    "pole-number": dict(ar="4:3", res="2k", prompt=(
        "Close-up photograph of a grey painted steel street-light pole on a sidewalk in a Russian city in soft evening light. At about 1.7 metres "
        "height a small white rectangular metal plate is screwed to the pole, and on the plate the pole number is stenciled in bold black digits "
        "exactly: 17-034. The plate is sharp and clearly readable, the background street is softly blurred with warm bokeh of other lamps. "
        "Photorealistic, 50mm lens, no other text anywhere."), ),
    "about-crew": dict(ar="16:9", res="4k", prompt=(
        "Documentary photo: a white utility truck with a hydraulic aerial lift, a dark navy stripe along its side, the bucket raised to the head "
        "of a street lamp at dusk. A lineman in a dark navy work jacket with silver reflective stripes and a white safety helmet replaces the "
        "lamp head, seen from behind and in profile, face not visible. Russian city street in Kirov, other lamps along the street already glowing "
        "warm yellow, orange beacon on the truck roof." + PHOTO)),
    "construction": dict(ar="16:9", res="4k", prompt=(
        "Photo of newly installed modern LED street lights on grey steel poles along a freshly paved road on the outskirts of Kirov at dusk, the "
        "lights just switched on and forming a long perspective line of warm dots, fresh soil and gravel at the pole bases, a backfilled cable "
        "trench along the roadside, birch trees and low private houses in the background. No people." + PHOTO)),
    "news-severnaya": dict(ar="3:2", res="2k", prompt=(
        "Evening photo of a residential street in a Russian city leading to a three-storey school building, a new row of LED street lamps "
        "illuminates the sidewalk and the road evenly, two small distant figures of pupils with backpacks walking, autumn, bare trees." + PHOTO)),
    "news-storm": dict(ar="3:2", res="2k", prompt=(
        "Night photo after a windstorm in a Russian city: a white utility truck with an aerial lift and flashing orange beacon, two workers in "
        "dark navy uniforms with reflective stripes repairing an overhead street lighting line, broken tree branches lying on the wet road, "
        "some street lamps already restored and glowing, faces not visible." + PHOTO)),
    "news-site": dict(ar="3:2", res="2k", prompt=(
        "Photo: a hand holding a modern smartphone on a dark evening street next to a street-light pole. The phone screen shows a clean mobile "
        "web interface: dark navy top bar, a large rounded yellow button, a few simple grey input fields, abstract UI blocks only, no readable "
        "text. Warm bokeh of street lights in the background, shallow depth of field." + PHOTO)),
    "panorama": dict(ar="21:9", res="4k", prompt=(
        "Panoramic photograph of the city of Kirov, Russia, at dusk seen from across the Vyatka river: the city on a high river bank with "
        "silhouettes of Orthodox church domes and a bell tower among trees and apartment blocks, the embankment street lamps turning on as a "
        "line of warm yellow dots mirrored in the calm dark river, deep navy sky with a last thin orange glow on the horizon." + PHOTO)),
    "not-found": dict(ar="16:9", res="2k", prompt=(
        "Night photo of an empty residential street in a Russian regional city (Soviet five-storey apartment blocks, bare birches) with a "
        "row of simple modern LED street lamps on grey poles along the right sidewalk. Every lamp glows warm yellow EXCEPT the third lamp "
        "from the camera, which is completely dark and switched off, so the asphalt under it is a clear patch of darkness between two "
        "pools of warm light. Calm, slightly moody, no people, no cars." + PHOTO)),
    "dispatch": dict(ar="3:2", res="2k", prompt=(
        "Interior photo of a municipal street-lighting dispatch control room at night: a dispatcher seen from behind wearing a headset sits at "
        "a desk with three monitors showing a dark city map with glowing yellow dots and simple charts, a large wall screen with the same dark "
        "map, the room is dim and lit by the screens, navy and warm yellow tones, no readable text on screens, face not visible."
        " Photorealistic, natural colors, no logos, no watermark.")),
    "og": dict(ar="16:9", res="2k", model="gpt_image_2_5", quality="xhigh", background="opaque",
               refs=["generated/logo-vertical.png"], prompt=(
        "Social media cover image for a municipal street-lighting service. Solid deep navy #14213D background. A soft trapezoid cone of warm "
        "yellow light (#FFB81C, gentle gradient to transparent) falls diagonally from the top right corner. On the left half, the logo from the "
        "reference image redrawn for a dark background: poles and wave line in white, lamp dots in yellow #FFB81C, wordmark КИРОВ СВЕТ in white "
        "bold geometric capitals. Under the logo the slogan in white clean sans-serif: Светло в каждом квартале. Flat, minimal, lots of "
        "negative space, crisp vector look, no other text.")),
    "sticker": dict(ar="4:5", res="2k", refs=["refs/logo-piksel-k.jpg"], prompt=(
        "Photorealistic close-up of a rectangular vinyl sticker on a grey steel street-light pole at dusk. The sticker has a deep navy #14213D "
        "background. At the top the 3x3 pixel grid letter K logo from the reference image, with the black cells replaced by white and the "
        "yellow cells in #FFB81C. In the middle a clean white QR code. Under it the large white text: Не горит? Наведите камеру. At the "
        "bottom small white digits: опора 17-034. Crisp print, slight reflections, softly blurred warm street lights behind.")),
    "aerial-lines": dict(ar="21:9", res="4k", prompt=(
        "Abstract top-down aerial view of a city at night reduced to a minimal graphic: thin dark twilight-blue street lines on a deep navy "
        "#14213D background, and along the streets evenly spaced tiny glowing warm yellow dots like street lamps seen from above, a gentle "
        "curving river band. Very dark overall, calm, lots of empty navy space, subtle, suitable as a website section background." + FLAT)),
}

LOGO_BASE = (
    "Symbol: eight thin vertical street-lamp poles of different heights standing side by side, each topped by a round solid lamp dot; "
    "the pole tops form a city-skyline rhythm, the tallest pole in the middle. The poles stand on one smooth wave line (the Vyatka river), "
    "each pole ends with a tiny gap just above the wave. All strokes equal thickness with rounded ends. "
    "Exactly match the proportions and pole heights of the reference logo. Perfectly crisp flat vector geometry, no gradients, no shadows, "
    "no glow, no 3D, no mockup, no extra text."
)
LOGOS = {
    "logo-vertical-t": dict(**GPT, ar="1:1", res="2k", refs=["generated/logo-vertical.png"], prompt=(
        "Recreate the reference logo exactly, as a clean vector logo. " + LOGO_BASE +
        " Colors: poles, wave and wordmark deep navy #14213D, lamp dots #FFB81C. Below the symbol the wordmark КИРОВ СВЕТ in bold geometric "
        "capitals like Montserrat Bold; under it one line СЛУЖБА НАРУЖНОГО ОСВЕЩЕНИЯ ГОРОДА КИРОВА in medium capitals, slate #5B6475." + CUTOUT)),
    "logo-horizontal-t": dict(**GPT, ar="21:9", res="2k", refs=["generated/logo-vertical.png"], prompt=(
        "Horizontal version of the reference logo. " + LOGO_BASE +
        " The symbol on the left; to the right of it the wordmark in two lines: КИРОВ on the first line and СВЕТ on the second line, bold geometric "
        "capitals like Montserrat Bold, left aligned, the two lines together as tall as the symbol. Colors: poles, wave and wordmark deep navy "
        "#14213D, lamp dots #FFB81C." + CUTOUT)),
    "logo-horizontal-dark-t": dict(**GPT, ar="21:9", res="2k", refs=["generated/logo-vertical.png"], prompt=(
        "Horizontal version of the reference logo for dark backgrounds. " + LOGO_BASE +
        " The symbol on the left; to the right the wordmark in two lines КИРОВ / СВЕТ, bold geometric capitals like Montserrat Bold, left aligned. "
        "Colors: poles, wave and wordmark pure white #FFFFFF, lamp dots #FFB81C." + CUTOUT)),
    "logo-mark-t": dict(**GPT, ar="1:1", res="2k", refs=["generated/logo-vertical.png"], prompt=(
        "Only the symbol of the reference logo, without any lettering. " + LOGO_BASE +
        " Colors: poles and wave deep navy #14213D, lamp dots #FFB81C. Centered." + CUTOUT)),
    "pixel-k-t": dict(**GPT, ar="1:1", res="2k", refs=["refs/logo-piksel-k.jpg"], prompt=(
        "Only the 3x3 square grid mark from the reference image, without any lettering: nine equal squares with equal small gaps. "
        "Left column: three squares deep navy #14213D. Middle column: top light grey #E4E7EC, middle yellow #FFB81C, bottom light grey #E4E7EC. "
        "Right column: top yellow #FFB81C, middle light grey #E4E7EC, bottom yellow #FFB81C. Sharp square corners, flat vector." + CUTOUT)),
}

# Второй проход: иллюстрации в стиле owner-street (он передаётся как референс стиля).
JOBS_STYLE = {
    "owner-yard": dict(**GPT, ar="4:3", res="2k", refs=["generated/owner-street.png"], prompt=(
        "Same illustration style and palette as the reference image. An inner courtyard of Soviet five-storey apartment buildings at night: "
        "small lamps above the entrance doors cast yellow light cones on the porches, a bench, a small playground, a parked car, lit windows. The scene is a compact rounded vignette." + FLAT + CUTOUT)),
    "owner-traffic": dict(**GPT, ar="4:3", res="2k", refs=["generated/owner-street.png"], prompt=(
        "Same illustration style and palette as the reference image. A city intersection at night with traffic lights on poles (one shows a "
        "green signal, one red), a pedestrian crossing, a road sign pole without any text, a highway lamp in the distance, a small bus silhouette. The scene is a compact rounded vignette." + FLAT + CUTOUT)),
    "chey-isometric": dict(**GPT, ar="16:9", res="4k", refs=["generated/owner-street.png"], prompt=(
        "Same illustration style and palette as the reference image, but isometric view. A city block at night: a main avenue lined with tall "
        "street lamps with yellow light cones, an inner courtyard of apartment buildings with small lamps above the entrance doors, and an "
        "intersection with traffic lights. Clear separation between the avenue, the courtyard and the intersection. The block floats as an isometric "
        "island." + FLAT + CUTOUT)),
}


def download(url, target):
    # curl вместо urllib: у python.org-сборки на macOS нет системных сертификатов
    subprocess.run(["curl", "-sSfL", "-o", str(target), url], check=True)


def recent_jobs():
    """Готовые задания из истории — чтобы не генерировать повторно после сбоя скачивания."""
    proc = subprocess.run(["higgsfield", "generate", "list", "--image", "--size", "100", "--json"],
                          capture_output=True, text=True)
    try:
        items = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    done = {}
    for it in items:
        prompt = (it.get("params") or {}).get("prompt")
        if it.get("status") == "completed" and it.get("result_url") and prompt:
            done.setdefault((it.get("job_type"), prompt), it["result_url"])
    return done


HISTORY = {}


def run(name, job):
    target = OUT / f"{name}.png"
    if target.exists():
        return name, "exists"
    model = job.get("model", "nano_banana_pro")
    cached = HISTORY.get((model, job["prompt"]))
    if cached:
        download(cached, target)
        return name, f"from history {cached}"
    cmd = ["higgsfield", "generate", "create", model,
           "--prompt", job["prompt"], "--aspect_ratio", job["ar"], "--resolution", job["res"],
           "--wait", "--wait-timeout", "20m", "--json"]
    if model == "gpt_image_2_5":
        cmd += ["--quality", job.get("quality", "xhigh"), "--background", job.get("background", "transparent")]
    for ref in job.get("refs", []):
        cmd += ["--image", str(ROOT / ref)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return name, f"error: {proc.stderr.strip()[-400:]}"
    try:
        data = json.loads(proc.stdout)
        item = data[0] if isinstance(data, list) else data
        url = item["result_url"]
    except Exception as exc:  # noqa: BLE001
        return name, f"parse error: {exc}: {proc.stdout[-300:]}"
    download(url, target)
    return name, url


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    prompts_file = ROOT / "prompts.json"
    prompts = json.loads(prompts_file.read_text()) if prompts_file.exists() else {}
    HISTORY.update(recent_jobs())

    for stage in ({**JOBS, **LOGOS}, JOBS_STYLE):
        todo = {k: v for k, v in stage.items() if not only or k in only}
        if not todo:
            continue
        with ThreadPoolExecutor(max_workers=10) as pool:
            for name, result in pool.map(lambda kv: run(*kv), todo.items()):
                print(f"{name}: {result}", flush=True)
                prompts[name] = todo[name]
        prompts_file.write_text(json.dumps(prompts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
