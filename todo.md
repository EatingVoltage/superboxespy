# To do

Things that need Samuel at the laser or his answer. The plans and their reasons are in `.grill/face-editor.md`.

- [ ] **Cut the CANVAS lid** (the face editor's first test cut). The files are in
      `C:\Projects\Laser lightburn\CANVAS STARTER KIT\` (`.sbox` and `.lbrn2`). The lid is on sheet 1: about 6.6 min,
      0.7 of it engraving, with burn X 0.185 / Y 0.15 (the measured profile).
- [ ] **Say what makes that cut right.** The proposal, still unanswered: the title reads cleanly from arm's length;
      the 0.8 mm crosshatch is even, with no scorching and no cutting into the wood; the logo's double lines stay
      apart; nothing reaches the finger joints. Whatever is off gets fixed in the editor (hatch spacing, outline instead
      of hatch, sizes).
- [ ] **Cut a flip registration test** before any real two-sided job (inside faces). Fit a corner stop at the bed's
      lower left. Run the page "Sheet N: inside first", turn the sheet over left to right into the same stop, then run
      "Sheet N". Check how far the inside engraving lands from where it should; a sheet that isn't 297 mm wide shifts
      it by the difference.
- [ ] **Trim `eatingVoltage logo.lbrn2`** in `C:\Projects\eating voltage Fonts\logos` to one logo: the copy holds it
      twice (one framed), and one file is one logo in the library (`.grill/logo-library.md`).
- [ ] **An ELEMENTS mark as a file of its own** in the logos folder, when you want it on a box: `elements Promo.lbrn2`
      is a poster.
- [ ] **A logo's fill next to hatch** (logo library): a logo 20 mm high or less fills its Scan shapes on FILL, a taller
      one is hatched. Check on a cut that both read right and the fill's time is fine.
- [ ] **Cut the symbol test sheet** (`.grill/symbol-library.md`): `C:\Projects\Laser lightburn\SYMBOL TEST\00_symbol-test.lbrn2`,
      about 10 min (6.8 of it FILL), preview `00_symbol-test.png`. Six plates (usb, midi-port, power, headphones,
      screw, circuit-resistor), each at 5, 8, 12 and 20 mm, LINE over SOLID. Report: the smallest size that still
      reads in each (MIDI's five pins, the screw's thread, the resistor's zigzag), whether LINE or SOLID should be the
      default, and anything that chars into a blob or comes out too faint. That sets the smallest size the app allows
      and the default style. Rebuild: `.venv/Scripts/python scripts/symbol_test_sheet.py "C:\Projects\Laser lightburn\SYMBOL TEST"`.
