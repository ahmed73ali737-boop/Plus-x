// UHEF help engine contract: route detection mirrors web/app.mjs, the bot answers only from the
// knowledge and refuses otherwise, and the support report never carries tokens or typed numbers.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
const require = createRequire(import.meta.url);
const H = require('../web/uhef-help.js');
const K = JSON.parse(readFileSync(new URL('../web/uhef-knowledge.json', import.meta.url), 'utf8'));
const loc = pathname => ({pathname, hash: ''});

const cases = [
  ['/', 'public.platform'], ['/anything', 'public.platform'], ['/e/demo', 'public.event'], ['/e/demo/p/agency-01', 'public.agency'],
  ['/e/demo/guest', 'guest.register'], ['/e/demo/guest/G-1234', 'guest.pass'], ['/e/demo/scan', 'gate.scan'], ['/e/demo/register', 'invite.register'],
  ['/invite/tok', 'invite.rsvp'], ['/live/demo', 'live.wall'], ['/certificate/tok', 'cert.access'], ['/verify/certificate/S1', 'cert.verify'],
  ['/certificates', 'selfcert.admin'], ['/certificates/request/t', 'selfcert.request'], ['/certificates/receive/t', 'selfcert.receive'], ['/certificates/verify/t', 'selfcert.verify'],
  ['/start', 'access.start'], ['/account', 'account.profile'], ['/account/signup', 'account.signup'], ['/account/request', 'account.request'], ['/account/invite', 'account.invite'],
  ['/admin', 'admin.login'],
];
for (const [path, key] of cases) { assert.equal(H.screenOf(loc(path)), key, path); assert.ok(K.screens[key], key + ' documented'); }
assert.equal(H.screenOf(loc('/admin'), {admin: 'password'}), 'admin.password');
assert.equal(H.screenOf(loc('/admin'), {admin: 'devices'}), 'admin.devices');
assert.equal(H.screenOf(loc('/e/demo'), {error: true}), 'app.error');

assert.deepEqual(H.problems(K, Object.keys(K.screens)), []);
const broken = structuredClone(K); broken.screens['gate.scan'].parts[1].use = []; broken.screens['admin.devices'].elements.device_name.howTo = '';
const gaps = H.problems(broken, Object.keys(K.screens)).join('\n');
assert.match(gaps, /gate\.scan: part .* has no roadmap/); assert.match(gaps, /admin\.devices: field device_name lacks howTo/);
assert.deepEqual(H.problems(K, ['admin.ghost']), ['admin.ghost: not documented']);

const items = H.passages(Object.keys(K.screens).map(k => H.model(K, k)));
const hit = H.ask('هل يظهر رقم هاتفي في QR؟', items, 'guest.register');
assert.ok(hit.length && hit[0].screen === 'guest.register', 'bot answers from the guest card screen');
assert.match(hit[0].text, /لا يوضع داخل QR/);
assert.deepEqual(H.ask('طقس مدينة طوكيو غدا', items, 'guest.register'), [], 'bot refuses an undocumented question');

const scan = H.journeysOf(K, 'gate.scan').map(j => j.id);
assert.ok(scan.includes('guest-admission') && scan.includes('invitation-rsvp'));

const r = H.report({type: 'bug', name: 'x', screen: 'invite.rsvp', page: K.screens['invite.rsvp'].route, description: 'رقمي 777123456 وبريدي a.b@example.com لا يعمل', at: '2026-11-04T00:00:00Z'});
assert.ok(!/777123456|example\.com/.test(r.description), 'typed numbers and e-mails are masked');
assert.match(r.description, /screen=invite\.rsvp page=\/invite\/:token at=2026-11-04T00:00:00Z/);
console.log(JSON.stringify({status: 'passed', routes: cases.length, screens: Object.keys(K.screens).length, journeys: Object.keys(K.journeys).length}));
