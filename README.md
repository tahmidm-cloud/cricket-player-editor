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

## Bowling style auto-fill

The editor can infer `bowlingHand` and `bowlingType` from `bowlingStyle`.

Examples:

- `Right-arm fast-medium` → `bowlingHand: right`, `bowlingType: pace`
- `Left-arm fast` → `bowlingHand: left`, `bowlingType: pace`
- `Off Break` → `bowlingHand: right`, `bowlingType: spin`
- `Slow left-arm orthodox` → `bowlingHand: left`, `bowlingType: spin`
- `Legbreak googly` → `bowlingHand: right`, `bowlingType: spin`

Use the **Auto-Fill Bowling** button to update everyone from their bowling style.
When you manually edit a player's `bowlingStyle`, that player's bowling hand/type update automatically.

## Local save

This version has browser local save.

Buttons:

- **Save Local Copy**: saves your current work in the browser.
- **Load Local Save**: reloads the saved browser copy later.
- **Clear Local Save**: removes the browser saved copy.
- **Download Updated JSON**: creates the final JSON file you should use in your app.

The editor also auto-saves shortly after edits.

Important: local save is stored only in that browser/device. If you switch phone/computer, clear browser data, or use private browsing, the saved copy may not be there. Always download the final updated JSON when finished.

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

This editor does not upload your JSON anywhere. It reads the file inside the browser, saves progress in browser storage, and downloads a new edited copy.
