# Cricket Player Profile Editor

A GitHub Pages-ready website for editing your cricket `players.json`.

## What this website edits

It edits only:

- `name`
- `fullName`
- `role`
- `battingHand`
- `bowlingHand`
- `bowlingType`
- `bowlingStyle`
- `nationalFormats`
- `formatStatus`
- player deletion

It preserves the rest of each player object.

## Important format logic

Use this meaning:

```json
"nationalFormats": {
  "test": true,
  "odi": true,
  "t20": false
},
"formatStatus": {
  "test": "eligible",
  "odi": "eligible",
  "t20": "retired"
}
```

- `eligible` = player can be selected in that format.
- `retired` = player cannot be selected in that format.
- `unavailable` = not selectable unless you change it.

This fixes the issue where a player has not played a format yet but could still be selected later.

Example:

- Abhishek Sharma type player: eligible in Test, ODI, and T20 if you want him selectable.
- Virat Kohli type partial retirement: retired formats are blocked, but ODI can stay eligible.

## Game selection helper

Use this in your game/team selection code:

```js
function canSelectForFormat(player, format) {
  const status = player?.formatStatus?.[format];

  if (status === "retired") return false;
  if (status === "eligible") return true;

  return player?.nationalFormats?.[format] === true;
}
```

## GitHub Pages setup

1. Create a new GitHub repository.
2. Name it something like `cricket-player-editor`.
3. Upload these files:
   - `index.html`
   - `style.css`
   - `app.js`
4. Go to your repository on GitHub.
5. Click **Settings**.
6. Click **Pages**.
7. Under **Build and deployment**, choose:
   - Source: **Deploy from a branch**
   - Branch: **main**
   - Folder: **/root**
8. Click **Save**.
9. Wait a minute.
10. GitHub will give you a website link.

## iPhone 15 Pro compatibility

This site is responsive and optimized for small screens around 393px wide, including iPhone 15 Pro.

## Privacy note

This editor does not upload your JSON anywhere. It reads the file inside the browser and downloads a new edited copy.
