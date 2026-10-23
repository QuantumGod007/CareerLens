export const $ = id => document.getElementById(id);
export function node(tag, attributes = {}, ...children) {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value !== undefined && value !== null) element.setAttribute(name, String(value));
  }
  for (const child of children.flat()) {
    if (child !== undefined && child !== null) element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}
export function button(label, action, className = 'text-button') {
  const element = node('button', {type: 'button', class: className}, label);
  element.addEventListener('click', action);
  return element;
}
export function empty(title, message) {
  return node('div', {class: 'empty'}, node('h3', {}, title), node('p', {}, message));
}
export function date(value, short = false) {
  if (!value) return 'Not refreshed yet';
  const time = new Date(value);
  return time.toLocaleString('en-IN', short ? {day: 'numeric', month: 'short'}
    : {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
}
export const words = value => value.toLowerCase().replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
export function pill(label, kind = 'neutral') { return node('span', {class: `pill ${kind}`}, label); }
export const taskKind = task => ({SUCCEEDED: 'good', FAILED: 'bad', CANCELLED: 'neutral', WAITING: 'warning'}[task.status] || 'neutral');
export function company(name) {
  return node('span', {class: 'company-logo', 'aria-hidden': 'true'}, name.slice(0, 1).toUpperCase());
}
export function officialURL(value, apply = false) {
  try {
    const url = new URL(value);
    const pattern = apply ? /^\/drivetrain\/[0-9a-f-]{36}\/apply$/i : /^\/drivetrain\/[0-9a-f-]{36}$/i;
    if (url.protocol === 'https:' && url.hostname === 'jobs.lever.co' && !url.port && !url.username
        && !url.password && !url.search && !url.hash && pattern.test(url.pathname)) return url.href;
  } catch { /* Untrusted destination: render no link. */ }
  return null;
}
