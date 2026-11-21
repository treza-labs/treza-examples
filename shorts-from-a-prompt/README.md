# A Short from one prompt

[`make_short.py`](make_short.py) turns a topic into a finished 18 second vertical Short: a voiceover, three clips, a composed music bed and burned-in captions, at 1080x1920. It needs only `requests`.

1. **Script.** A small pipeline in your account writes a 35 to 45 word voiceover, reads it aloud (Treza's default voice) and plans three shots that illustrate it. The script creates this pipeline on its first run, named `Short script (treza-examples v1)`, and reuses it after that. It is built with `create_pipeline` from four node types: Text Input, Text Generation, Text to Speech and Output.
2. **Clips.** `make_video` renders each shot as a silent 6 second 9:16 clip. The voiceover and music are the sound, and silent clips cost less.
3. **Assembly.** `assemble_video` cuts the three clips together with fades, lays the voiceover over them, composes a music bed from `--music` and ducks it under the voice, burns in captions and fades out the ending.

## Cost

| Step | About |
| --- | --- |
| Script and voiceover | $0.18 |
| 3 clips, 6 seconds each, Veo 3.1 Lite, no sound | 3 x $0.25 = $0.75 |
| Assembly with music and captions | free once your account has bought credits |
| **Total** | **$0.93** |

The script prints this quote, with Treza's real prices, before it spends anything, and only spends with `--yes`. It stops if the total is over `--max-cost` (default $2.00) or your balance is short. With `--yes`, each clip is quoted again before it starts and must fit in what is left of `--max-cost`.

## Run

```bash
pip install -r requirements.txt
export TREZA_API_KEY="treza_live_..."   # see ../README.md#get-a-key
python make_short.py "how octopuses taste with their arms"         # the quote only, nothing spent
python make_short.py "how octopuses taste with their arms" --yes   # make it
```

| Option | Default | What it does |
| --- | --- | --- |
| `--yes` | off | Make the Short. Without it, only the quote is shown |
| `--max-cost` | `2.00` | The most the whole Short may cost, in USD |
| `--seconds` | `6` | Length of each clip: `6` or `8` |
| `--music` | warm cinematic underscore | What the composed music bed sounds like |
| `--out` | `short.mp4` | Where to save it |

## Expected output

```
$ python make_short.py "how octopuses taste with their arms" --yes

A Short about: how octopuses taste with their arms (18 seconds)
  Script and voiceover                        $0.18
  3 clips, 6s each, Veo 3.1 Lite, no sound    3 x $0.25 = $0.75
  Assembly: music, captions, 1080x1920        free once your account has bought credits
  Total                                       about $0.93  (max cost $2.00, balance $12.40)

Writing and recording the voiceover...
  Voiceover: Octopuses taste with their arms. ...
  Clip 1: Macro shot of an octopus arm curling over a mossy rock, ...
  Clip 2: ...
  Clip 3: ...
Rendering the clips...
Assembling the Short...
  18 seconds, free

Saved short.mp4 (... bytes). Spent about $0.93.
Link: https://media.trezalabs.com/...
```

It takes a few minutes: the script run first, then the three clips side by side, then the assembly.

## Good to know

- The voiceover has to fit the clips. Treza holds the last frame up to 3 seconds for a voice to finish, and refuses an assembly whose voice runs longer, with nothing charged. The writer is asked for 35 to 45 words, about 15 seconds. Use `--seconds 8` for more room.
- If a step fails after the clips are made, the script prints their links. They stay in your Treza library, and you can pass them to `assemble_video` yourself.
- To change the writing or the voice, open the `Short script (treza-examples v1)` pipeline in Treza and edit it there. The script finds it by name.
