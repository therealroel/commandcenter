// Unit test for computeVisible, extracted verbatim from templates/index.html.
// Verifies that collapsing the layout keeps the active/focused channel.

function computeVisible(currentVisible, targetCount, focused) {
  let vis;
  if (targetCount >= currentVisible.length) {
    vis = [...currentVisible];
    for (let i = 0; i < 3 && vis.length < targetCount; i++) {
      if (!vis.includes(i)) vis.push(i);
    }
  } else {
    vis = [];
    if (currentVisible.includes(focused)) vis.push(focused);
    for (const pid of currentVisible) {
      if (vis.length >= targetCount) break;
      if (!vis.includes(pid)) vis.push(pid);
    }
  }
  return [...new Set(vis)].filter(i => i >= 0 && i < 3).sort((a, b) => a - b);
}

let pass = 0, fail = 0;
function eq(a, b) {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}
function check(name, got, want) {
  if (eq(got, want)) { pass++; console.log(`✓ ${name}`); }
  else { fail++; console.log(`✗ ${name}\n    got=[${got}] want=[${want}]`); }
}

// THE BUG: two channels open [0,1], panel 1 active, collapse to 1 channel.
// Must keep channel 1, not snap back to 0.
check("2->1 keep active panel 1", computeVisible([0, 1], 1, 1), [1]);
check("2->1 keep active panel 0", computeVisible([0, 1], 1, 0), [0]);

// Three channels, collapse to 1 keeping the focused one.
check("3->1 keep active panel 2", computeVisible([0, 1, 2], 1, 2), [2]);
check("3->1 keep active panel 1", computeVisible([0, 1, 2], 1, 1), [1]);

// Collapse 3->2 keeps focused + next lowest visible.
check("3->2 keep active panel 2", computeVisible([0, 1, 2], 2, 2), [0, 2]);
check("3->2 keep active panel 0", computeVisible([0, 1, 2], 2, 0), [0, 1]);

// Focused panel not in the visible set (edge): fall back to lowest slots.
check("2->1 focus outside visible", computeVisible([0, 1], 1, 2), [0]);

// Growing keeps current and fills lowest free slots.
check("1->2 from [1] grows", computeVisible([1], 2, 1), [0, 1]);
check("1->3 from [2] grows", computeVisible([2], 3, 2), [0, 1, 2]);
check("2->3 from [0,2] grows", computeVisible([0, 2], 3, 0), [0, 1, 2]);

// No-op-ish: same count returns a normalized set.
check("2->2 keeps both", computeVisible([0, 1], 2, 0), [0, 1]);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
