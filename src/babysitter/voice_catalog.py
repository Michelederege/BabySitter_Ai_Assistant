"""Every voice BabySitter can speak with: more than 200, all free, all on this PC.

Data only. The model packs, the engines, and the Voice tab read this list.

- Kokoro: 28 English voices, already in the Kokoro voice file (Apache 2.0).
- Supertonic: 10 voice styles, in its pack.
- Piper: 26 single English voices, and four packs with many speakers:
  VCTK (109 British and Irish accents), ARCTIC (18), Aru (12), Semaine (4).
  Each Piper pack downloads only after a yes and is pinned to a SHA-256.

Each voice's licence is noted. Piper's single voices come from public
datasets; each pack carries its MODEL_CARD with the exact terms. A voice
that imitates a real person or a character is left out (GLaDOS is not here).
"""

from __future__ import annotations

from dataclasses import dataclass

SHERPA_TTS = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"


@dataclass(frozen=True)
class Voice:
    name: str  # shown on the Voice tab and saved in voice.json
    engine: str  # "kokoro", "piper", or "supertonic"
    accent: str
    pack: str = ""  # the model pack, for Piper and Supertonic
    speaker: str = ""  # the speaker inside a pack, or the Kokoro voice id
    licence: str = ""


# (pack id, label, accent, archive, sha256)
PIPER_SINGLES = [
    [
        "piper-alan",
        "Alan",
        "British",
        "en_GB-alan-medium",
        "a48d4017da0f77668b27bed63fe6e04dd64c6397e1fadad4f460efb0ef7c9012"
    ],
    [
        "piper-alba",
        "Alba",
        "Scottish",
        "en_GB-alba-medium",
        "fcd45962906933eec4431d3688f7d74aaac8713c87c6717f91fd3b23463aa1a1"
    ],
    [
        "piper-cori",
        "Cori",
        "British",
        "en_GB-cori-medium",
        "49c9a5361bbdd95d7ca9687c4de11e5908481f65e7c7c368960df79949fdac2b"
    ],
    [
        "piper-dii",
        "Dii",
        "British",
        "en_GB-dii-high",
        "1cc07423996e0aadb19ac62a08c2f2760362dafb3b5598d2f301ca789edacf86"
    ],
    [
        "piper-jenny",
        "Jenny",
        "British",
        "en_GB-jenny_dioco-medium",
        "a0888024569bafbefc05a4b48ddf8419d8dbbf3205f4af37cf7c6f1a87cc20c5"
    ],
    [
        "piper-miro-gb",
        "Miro (British)",
        "British",
        "en_GB-miro-high",
        "c42907615e1a95bb69a85674f9d7979eeb2352c40fe86a0ae84d5479149c03d1"
    ],
    [
        "piper-northern-male",
        "Northern English male",
        "British",
        "en_GB-northern_english_male-medium",
        "2bb2c1e709f58c11f17c693b3b38f500e110e7f54f2651774ec48b8d41f12c55"
    ],
    [
        "piper-southern-female",
        "Southern English female",
        "British",
        "en_GB-southern_english_female-medium",
        "cea2dcbe8a8e2a44a4bab6824e10dc38fcd5cf84458e8b3f3e5be1c5fb804512"
    ],
    [
        "piper-southern-male",
        "Southern English male",
        "British",
        "en_GB-southern_english_male-medium",
        "f5525a6fd9a2fc0ab930ea70da6e3bcf207922a9f701acb0324ba2f59e4ca9ba"
    ],
    [
        "piper-amy",
        "Amy",
        "American",
        "en_US-amy-medium",
        "9a5d1fc497f85e8022b785bff5f8105203b1e33099ee6265203efc70b0cb0264"
    ],
    [
        "piper-bryce",
        "Bryce",
        "American",
        "en_US-bryce-medium",
        "f35bb77ddecdf229798e850d1c77ded839d4179879be8b90da5f82e7beb538f2"
    ],
    [
        "piper-danny",
        "Danny",
        "American",
        "en_US-danny-low",
        "4e989aed6e2d11ed681f099df1e8fedca557f006205358814d6298a7f8f2e034"
    ],
    [
        "piper-hfc",
        "HFC female",
        "American",
        "en_US-hfc_female-medium",
        "3fffdceb0c65bd9415a085d09c3cb88cc82f9d74a6ca453f8ce7fc5eaee81ff8"
    ],
    [
        "piper-hfc-male",
        "HFC male",
        "American",
        "en_US-hfc_male-medium",
        "76388f84acfca8ba5c0ed1636a26ada14c598abd52e76f110d4756fe326fc5f2"
    ],
    [
        "piper-joe",
        "Joe",
        "American",
        "en_US-joe-medium",
        "261b903a1fb2ce621e2b5b14233cd41223c3b9f9590f896c11daee4df22d9bd3"
    ],
    [
        "piper-john",
        "John",
        "American",
        "en_US-john-medium",
        "d90362cfa48e429d3096f644785184446145b6e38216f2eaf4c0601b8aad5a36"
    ],
    [
        "piper-kathleen",
        "Kathleen",
        "American",
        "en_US-kathleen-low",
        "3dd0adaf077e19de32876608c3ac3d4a0a46a6f06310cc7a5633b3b47d762cde"
    ],
    [
        "piper-kristin",
        "Kristin",
        "American",
        "en_US-kristin-medium",
        "c2206f572df2956c50b1ae3367eebce3853c663e890cba8048cd62b1e4dbe6c7"
    ],
    [
        "piper-kusal",
        "Kusal",
        "American",
        "en_US-kusal-medium",
        "e683c4a9a0c1ca28c81cbec77b51fe987cf70efa97edc3ace4c1783083012c33"
    ],
    [
        "piper-lessac",
        "Lessac",
        "American",
        "en_US-lessac-medium",
        "9e3febfacf0abf4270172d2958bcec246032b7e88efc2720840cc80c93de334e"
    ],
    [
        "piper-ljspeech",
        "LJ Speech",
        "American",
        "en_US-ljspeech-medium",
        "3dfb4b759d8be032a4903a9538d128b0fda2a06ab1de6cbc2d93a97e2dd83dba"
    ],
    [
        "piper-miro-us",
        "Miro",
        "American",
        "en_US-miro-high",
        "31678890d09520c5d09a480e2e01aaf355d7d005f8179899aed8fe0cae2a3ca1"
    ],
    [
        "piper-norman",
        "Norman",
        "American",
        "en_US-norman-medium",
        "1f32065d480abe9abc7c7f91442125d0b34c1cc065d1e600466cac408eabf3b8"
    ],
    [
        "piper-reza",
        "Reza Ibrahim",
        "American",
        "en_US-reza_ibrahim-medium",
        "025f5702bf39722782937aef5bc4ff9a1ef67fb0f1d0c0952c9c4ead25be19cc"
    ],
    [
        "piper-ryan",
        "Ryan",
        "American",
        "en_US-ryan-medium",
        "c546af78b6395b4e7c4ce1ed899438b64426a362f5d4ec5fecd090ded9ad7505"
    ],
    [
        "piper-sam",
        "Sam",
        "American",
        "en_US-sam-medium",
        "7bcfcf73d7eb3dc7d2cba41ef4b1474d08819b581bafa9e9200821d607b74639"
    ]
]

# (pack id, label, accent, archive, sha256, licence, speakers in the model's order)
PIPER_MULTI = [
    [
        "piper-vctk",
        "VCTK",
        "British and Irish accents",
        "en_GB-vctk-medium",
        "abafd35bdab0a72a3c6b947228ae3cccdf3624db83313c77d1abb5cbc75e1f64",
        "CC BY 4.0: credit the CSTR VCTK Corpus, University of Edinburgh.",
        [
            "p239",
            "p236",
            "p264",
            "p250",
            "p259",
            "p247",
            "p261",
            "p263",
            "p283",
            "p286",
            "p274",
            "p276",
            "p270",
            "p281",
            "p277",
            "p231",
            "p271",
            "p238",
            "p257",
            "p273",
            "p284",
            "p329",
            "p361",
            "p287",
            "p360",
            "p374",
            "p376",
            "p310",
            "p304",
            "p334",
            "p340",
            "p323",
            "p347",
            "p330",
            "p308",
            "p314",
            "p317",
            "p339",
            "p311",
            "p294",
            "p305",
            "p266",
            "p335",
            "p318",
            "p351",
            "p333",
            "p313",
            "p316",
            "p244",
            "p307",
            "p363",
            "p336",
            "p297",
            "p312",
            "p267",
            "p275",
            "p295",
            "p258",
            "p288",
            "p301",
            "p232",
            "p292",
            "p272",
            "p280",
            "p278",
            "p341",
            "p268",
            "p298",
            "p299",
            "p279",
            "p285",
            "p326",
            "p300",
            "s5",
            "p230",
            "p345",
            "p254",
            "p269",
            "p293",
            "p252",
            "p262",
            "p243",
            "p227",
            "p343",
            "p255",
            "p229",
            "p240",
            "p248",
            "p253",
            "p233",
            "p228",
            "p282",
            "p251",
            "p246",
            "p234",
            "p226",
            "p260",
            "p245",
            "p241",
            "p303",
            "p265",
            "p306",
            "p237",
            "p249",
            "p256",
            "p302",
            "p364",
            "p225",
            "p362"
        ]
    ],
    [
        "piper-arctic",
        "ARCTIC",
        "American and other accents",
        "en_US-arctic-medium",
        "caf83305b2fecc84491e9581f31ef2c81d4e1dacb8b76a4e481ad3fb6d4bf25c",
        "CMU ARCTIC licence: free to use, keep the notice.",
        [
            "awb",
            "rms",
            "slt",
            "ksp",
            "clb",
            "lnh",
            "aew",
            "bdl",
            "jmk",
            "rxr",
            "fem",
            "ljm",
            "slp",
            "aup",
            "ahw",
            "axb",
            "eey",
            "gka"
        ]
    ],
    [
        "piper-aru",
        "Aru",
        "British",
        "en_GB-aru-medium",
        "15b6e7a545d899167a688a054b95730ec8cdfd35d27d00bab1dc5234c4a451a0",
        "CC BY 4.0: credit the ARU speech corpus.",
        [
            "03",
            "06",
            "10",
            "01",
            "09",
            "08",
            "11",
            "05",
            "12",
            "02",
            "07",
            "04"
        ]
    ],
    [
        "piper-semaine",
        "Semaine",
        "British",
        "en_GB-semaine-medium",
        "b2a1e39062fce8f7fb14b7fa5fb93d89c58e3af2245270387f408099f5a2da9f",
        "CC BY-NC-SA 4.0: personal and non-commercial use only.",
        [
            "prudence",
            "spike",
            "obadiah",
            "poppy"
        ]
    ]
]

KOKORO_ENGLISH = [
    [
        "af_alloy",
        "Alloy"
    ],
    [
        "af_aoede",
        "Aoede"
    ],
    [
        "af_bella",
        "Bella"
    ],
    [
        "af_heart",
        "Heart"
    ],
    [
        "af_jessica",
        "Jessica"
    ],
    [
        "af_kore",
        "Kore"
    ],
    [
        "af_nicole",
        "Nicole"
    ],
    [
        "af_nova",
        "Nova"
    ],
    [
        "af_river",
        "River"
    ],
    [
        "af_sarah",
        "Sarah"
    ],
    [
        "af_sky",
        "Sky"
    ],
    [
        "am_adam",
        "Adam"
    ],
    [
        "am_echo",
        "Echo"
    ],
    [
        "am_eric",
        "Eric"
    ],
    [
        "am_fenrir",
        "Fenrir"
    ],
    [
        "am_liam",
        "Liam"
    ],
    [
        "am_michael",
        "Michael"
    ],
    [
        "am_onyx",
        "Onyx"
    ],
    [
        "am_puck",
        "Puck"
    ],
    [
        "am_santa",
        "Santa"
    ],
    [
        "bf_alice",
        "Alice"
    ],
    [
        "bf_emma",
        "Emma"
    ],
    [
        "bf_isabella",
        "Isabella"
    ],
    [
        "bf_lily",
        "Lily"
    ],
    [
        "bm_daniel",
        "Daniel"
    ],
    [
        "bm_fable",
        "Fable"
    ],
    [
        "bm_george",
        "George"
    ],
    [
        "bm_lewis",
        "Lewis"
    ]
]

SUPERTONIC_STYLES = ["F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5"]


def piper_packs() -> list[tuple[str, str, str, str]]:
    """(pack id, label, archive url, sha256) for every Piper pack."""
    packs = [(pid, f"Piper: {label}", SHERPA_TTS + f"vits-piper-{archive}.tar.bz2", sha) for pid, label, _a, archive, sha in PIPER_SINGLES]
    packs += [(pid, f"Piper {label} ({len(speakers)} voices)", SHERPA_TTS + f"vits-piper-{archive}.tar.bz2", sha)
              for pid, label, _a, archive, sha, _l, speakers in PIPER_MULTI]
    return packs


def catalog() -> list[Voice]:
    voices: list[Voice] = []
    for voice_id, label in KOKORO_ENGLISH:
        accent = "American" if voice_id[0] == "a" else "British"
        voices.append(Voice(f"Kokoro: {label}", "kokoro", accent, speaker=voice_id, licence="Apache 2.0"))
    for style in SUPERTONIC_STYLES:
        voices.append(Voice(f"Supertonic: {style}", "supertonic", "American", pack="supertonic", speaker=style,
                            licence="BigScience Open RAIL-M, with use limits; huggingface.co/Supertone/supertonic-3."))
    for pid, label, accent, _archive, _sha in PIPER_SINGLES:
        voices.append(Voice(f"Piper: {label}" if label != "Jenny" else "Piper: Jenny (British)", "piper", accent, pack=pid,
                            licence="See the MODEL_CARD in its pack."))
    for pid, label, accent, _archive, _sha, licence, speakers in PIPER_MULTI:
        for index, speaker in enumerate(speakers):
            voices.append(Voice(f"Piper {label}: {speaker}", "piper", accent, pack=pid, speaker=str(index), licence=licence))
    return voices
