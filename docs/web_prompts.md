# Prompts for the Gemini web app (gemini.google.com)

The API credits are used up, so the image-generation steps are done by hand in the Gemini web app (Nano Banana).
Workflow: paste a prompt as-is → download the result image → upload it to the Claude chat.
Claude handles the rest (pixel grid restore, palette, Aseprite assembly, critic review).

## Round 1: concept → base pixel sprite

### 1-A. Concept art (skip this if you already have your own concept image)

**Fox swordswoman**
```
Character concept art illustration, painterly digital painting (NOT pixel art): a young fox-eared wandering swordswoman with orange fox ears and a bushy orange fox tail, short white hair, a teal hooded short cloak, brown leather armor, a slim curved sword sheathed at her hip, boots. Full body, side view facing right, relaxed ready stance. Clean silhouette, plain light grey background, no text, no other characters.
```

**Stone boar (non-humanoid monster)**
```
Creature concept art illustration, painterly digital painting (NOT pixel art): a heavy four-legged boar-like monster whose back is covered by a thick shell of mossy grey stone plates, two big curved ivory tusks, small glowing orange eyes, short thick legs with hooves, a stubby tail, dark brown bristly hide on the belly and legs. Full body, side view facing right, standing. Clean silhouette, plain light grey background, no text, no other creatures.
```

### 1-B. Concept → pixel sprite (in the same chat, right after the concept, or attach the concept image)

**Fox swordswoman** (32 px tall)
```
Redraw this exact character as ONE pixel-art game sprite: side view facing right, exactly 32 art pixels tall, every art pixel a crisp 16x16 block on one grid, at most 16 colours, a dark 1-pixel outline, simple 2-3 tone shading per material, no anti-aliasing, no gradients, no dithering. Keep the concept's proportions, silhouette, key shapes and colour masses; simplify small details that would be noise at this size. Neutral standing pose with the hand near the sword hilt, the whole body visible, centred, on a flat magenta (#FF00FF) background. No text, no shadow, no other objects.
```

**Stone boar** (28 px tall, about 44 px long)
```
Redraw this exact creature as ONE pixel-art game sprite: side view facing right, exactly 28 art pixels tall and about 44 art pixels long, every art pixel a crisp 16x16 block on one grid, at most 16 colours, a dark 1-pixel outline, simple 2-3 tone shading per material, no anti-aliasing, no gradients, no dithering. Keep the concept's proportions, silhouette, key shapes and colour masses; simplify small details that would be noise at this size. Neutral standing pose, all four legs visible, centred, on a flat magenta (#FF00FF) background. No text, no shadow, no other objects.
```

What to send back: the **pixel sprite images (1-B) for both characters** (the concepts too, if you have them).

## Round 2: storyboards (after round 1)
Once the base sprites arrive, Claude makes a **template image** (the base sprite in the first cell of a grid) and a **per-cell prompt** for each animation:
fox idle / slash, boar idle / walk / charge, 5 in total. Attach the template image in the Gemini web app, paste the prompt, and send back the result.
(The shot lists are already designed: `samples/fox/plans/`, `samples/boar/plans/`, explained in `docs/creatures_plan.md`.)
