const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');

// Exercise the actual dialog renderer with a small DOM stand-in.
const html = fs.readFileSync(`${__dirname}/static/index.html`, 'utf8');
const source = html.slice(html.indexOf('function showConnection('), html.indexOf('async function operation('));
function dialog() {
  const elements = new Map();
  const element = (tag, textContent = '') => ({
    tag, textContent, children: [],
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    showModal() { this.open = true; },
  });
  const $ = id => {
    if (!elements.has(id)) elements.set(id, element(id));
    return elements.get(id);
  };
  const context = vm.createContext({$, text: element});
  vm.runInContext(source, context);
  return {show: context.showConnection, $, fields: () =>
    $('connectionCommands').children.map(box => box.children.map(child => child.textContent))};
}

test('Saga dialog identifies the selected session and provides its own port', () => {
  const view = dialog();
  view.show({client: 'saga', character: 'Hero', realm: 'test', host: '127.0.0.1', port: 8001, note: 'Attach in Saga.'});
  assert.equal(view.$('connectionHeading').textContent, 'Attach Hero in Saga');
  assert.deepEqual(view.fields(), [
    ['Character', 'Hero · Test'], ['Game', 'GemStone IV'], ['Host', '127.0.0.1'], ['Port', '8001'],
  ]);
  assert.equal(view.$('connectionNote').textContent, 'Attach in Saga.');
  assert.equal(view.$('connectionDialog').open, true);
});

test('switching back to connection details replaces Saga fields and heading', () => {
  const view = dialog();
  view.show({client: 'saga', character: 'Hero', realm: 'prime', host: '127.0.0.1', port: 8000});
  view.show({host: '127.0.0.1', port: 8012, note: 'Open a tunnel.', desktop_command: 'desktop', terminal_command: 'terminal', ssh_command: 'tunnel'});
  assert.equal(view.$('connectionHeading').textContent, 'Connect another client');
  assert.deepEqual(view.fields(), [
    ['Lich address', '127.0.0.1:8012'], ['Vellum desktop', 'desktop'],
    ['Vellum terminal', 'terminal'], ['SSH tunnel from another computer', 'tunnel'],
  ]);
});
