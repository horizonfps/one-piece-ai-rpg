# Player Guide — One Piece RPG

# Author's Note

One Piece RPG is a solo project made by me (horizon) where you, as the player, live through the One Piece canon story as a brand-new variable in the world. Unlike the usual take most people go for, the Straw Hat crew exists in this game — and the moment you set sail, they are leaving Egghead. Play however you want. Want to become Pirate King before Luffy? You can. Want to be a villain? You can too — the biggest limit in this game is your imagination. Unlike every other RPG, there is no dice rolling in front of you: every fight, chance encounter and drama is handled by the LLM, and you have full control over your own story.

My main goal has always been to deliver an enjoyable, fun story to every One Piece fan. I hope you like it — and pay close attention to the tutorial!

## Getting started

On the title screen you create a new campaign or open a saved one. Each campaign is an independent save (you can keep several).

### Character creation

Every character starts with a few points locked in.

- Everyone sets sail from the East Blue (Foosha)
- Everyone leaves for the sea at 17 years old
- Starting bounty is always 0

This makes the player always the youngest — 2 years younger than Luffy.

Beyond those fixed points, the character sheet is fully customizable:

- **Name, gender, weapon**: free text.
  - Note: naming your weapon after one that already exists in the One Piece world is not recommended — how the LLM reacts to duplicates in the world is untested. Getting creative and forging an original weapon is highly recommended.
- **Target tier**: `NORMAL`, `SKILLED` or `STRONG`. This is where you pick how hard you want the early game to be: STRONG is a very high level for most East Blue antagonists, while NORMAL gives you more dramatic moments, constant action and great power-up scenes.
- **Class**: defines how you fight. Fruit users who are cut off from their fruit (seastone) drop 1/2 tiers.
- **Traits**: rolled (2 to 5, drawn from a catalog). Unlimited rerolls. They can be edited; traits never act on your character's behalf, they only send signals.
  - E.g. the Glutton trait won't make your character walk off to eat on their own, but stay too long without food and their stomach will growl involuntarily.
- **Devil Fruit**: a delicate, carefully curated option — the original One Piece fruits are all here. I hand-picked every fruit that makes sense to have in the selection pool.
  - E.g. Gomu Gomu cannot be chosen; it would wreck Luffy's entire Nika story hook.
  - E.g. 2: Mera Mera could be included, since it only shows up in Dressrosa and the story barely changes: the Dressrosa tournament prize becomes a SMILE fruit instead of the Mera Mera, Sabo still comes to investigate and still meets Luffy — and in exchange for the downgrade, he grows more proficient in the Ryusoken fighting style.
- **Dream**: free text. The Director and the Narrator improvise hooks from it.

## Playing a turn

There is a text field and a selector with two action types:

### Do (DO)

An action in the world. Write what you do in 1st or 3rd person; put **speech between quotes** inside
the text:

```
I cross my arms and stare the man down. "Out of my way. I won't say it twice."
```

The Narrator renders exactly what you declared and **never speaks or acts for you**. If you wrote
no dialogue, your character acts in silence.

### Meta (META)

Out of character. Three uses:

- **Question**: clears up a doubt ("what does this NPC know about me?") without spending a turn.
- **Remember**: registers a permanent directive the game starts honoring:
  `remember: my father was a Marine vice admiral`
  The Narrator weaves it in without friction — the story is yours.
- **forget**: deactivates a registered directive.
- General questions.
  Who is the strongest in my crew?
  Who is the strongest on this island?

## The world reacts

- **Map**: read-only window into your position and discovered islands. Travel is decided by narrating.
- **Bounty & Nemesis**: public deeds earn bounty (with a few days of delay, like in canon). A
  **Marine nemesis** evolves while hunting you across the campaign. (Sorry Warner Bros)
- **News Coo**: the newspaper arrives from time to time with what happened in the world (and
  sometimes with you on the front page).
- **Den Den Mushi & Vivre Card**: long-distance communication. Paired NPCs can call you; the vivre
  card burns when its owner is in danger.
- **Ship, economy, techniques, alliances, per-faction reputation**: everything emerges from the
  narration and shows up in the HUD panels.

## HUD and editing (everything is editable)

The menu (☰) opens a drawer with tabs: **sheet, memory, techniques, inventory, ship, reputation,
alliances, comms, directives, newspaper, plots, ending**. Almost everything is **editable inline** —
name, dream, tier, alignment, techniques, memory, even a turn's narration. Editing **does not
advance the turn** nor rewrites memory; the next turn simply reads the new state.

There is also:

- **↻ regenerate narration** — re-runs the last turn, with a box where you can write what you want
  to be different from the previous generation
- **rewind narration** — goes back one turn if you want to redo an action (limit of 3)
- **devtools** — trace of every LLM call in the turn (input/output/token usage).

## Endings

There is no game-over by death (your character never dies to brute force). As alignment, bounty,
chaos, tier and the world mature, **possible endings** show up (Pirate King, Yonko, and others).
You choose when to close — the game generates a cinematic epilogue — and you can keep playing
afterwards (continue mode).

## If something goes wrong

- **"Claude Max subscription at its limit"**: your current window's quota ran out (it resets in
  hours). Nothing was lost; come back later and resume where you stopped.
- **"Couldn't narrate this input"**: the model refused to render that action (safety filter). Your
  action returns to the field; rephrase and try again. The campaign stays intact.
- **Generic error**: try again; nothing is persisted halfway.
