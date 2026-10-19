import { useSyncExternalStore } from 'react';
import english from './i18n-en.json';
import { createTranslator, hasChinese } from './translator';

// Interface language. The Chinese source stays the single source of truth: English is applied to the
// rendered DOM (text nodes and a few attributes) and undone when switching back. Content marked
// translate="no" (AI output, personal notes, video titles) and form fields are never rewritten.
export type Language = 'zh' | 'en';
type Memo = { source: string; shown: string };

const STORAGE_KEY = 'vp-language'; // Also read by the first-paint script in index.html.
const ATTRIBUTES = ['title', 'aria-label', 'placeholder', 'alt', 'aria-valuetext', 'aria-description', 'aria-roledescription', 'label'];
const FROZEN = '[translate="no"]'; // Nothing inside is rewritten.
const RAW = 'script, style, textarea, code, pre'; // Own attributes (e.g. placeholder) are translated, contents never.

const toEnglish = createTranslator(english);
const texts = new WeakMap<Text, Memo>();
const attributes = new WeakMap<Element, Map<string, Memo>>();
const listeners = new Set<() => void>();
let language: Language = storedLanguage();
let observer: MutationObserver | null = null;
let titleSource: string | null = null;

function storedLanguage(): Language {
  try { return localStorage.getItem(STORAGE_KEY) === 'en' ? 'en' : 'zh'; } catch { return 'zh'; }
}

export const getLanguage = () => language;
/** For text the DOM pass cannot reach, such as window.confirm or content inside translate="no". */
export const t = (text: string) => language === 'en' ? toEnglish(text) : text;

export function useLanguage(): Language {
  return useSyncExternalStore(subscribe, getLanguage, getLanguage);
}

export function setLanguage(next: Language) {
  if (next === language) return;
  language = next;
  try { localStorage.setItem(STORAGE_KEY, next); } catch { /* Still applies to this page. */ }
  apply();
  listeners.forEach(listener => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function apply() {
  document.documentElement.lang = language === 'en' ? 'en' : 'zh-CN';
  if (language === 'en') {
    titleSource ??= document.title;
    document.title = toEnglish(titleSource);
    visit(document.body);
    if (!observer) {
      observer = new MutationObserver(records => records.forEach(changed));
      observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRIBUTES });
    }
    return;
  }
  observer?.disconnect();
  observer = null;
  if (titleSource !== null) { document.title = titleSource; titleSource = null; }
  restore(document.body);
}

const textExcluded = (parent: Element | null) => !parent || parent.closest(`${FROZEN}, ${RAW}`) !== null;
const attributesExcluded = (element: Element) => element.closest(FROZEN) !== null || (element.parentElement?.closest(RAW) ?? null) !== null;

function visit(root: Node) {
  if (root.nodeType === Node.TEXT_NODE) {
    if (!textExcluded(root.parentElement)) translateText(root as Text);
    return;
  }
  if (root.nodeType !== Node.ELEMENT_NODE || attributesExcluded(root as Element)) return;
  if ((root as Element).matches(RAW)) { translateAttributes(root as Element); return; }
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, { acceptNode: accept });
  for (let node: Node | null = walker.currentNode; node; node = walker.nextNode()) {
    if (node.nodeType === Node.TEXT_NODE) translateText(node as Text);
    else translateAttributes(node as Element);
  }
}

function accept(node: Node) {
  if (node.nodeType !== Node.ELEMENT_NODE) return NodeFilter.FILTER_ACCEPT;
  const element = node as Element;
  if (element.matches(FROZEN)) return NodeFilter.FILTER_REJECT;
  if (element.matches(RAW)) { translateAttributes(element); return NodeFilter.FILTER_REJECT; }
  return NodeFilter.FILTER_ACCEPT;
}

function translateAttributes(element: Element) {
  for (const name of ATTRIBUTES) if (element.hasAttribute(name)) translateAttribute(element, name);
}

function changed(record: MutationRecord) {
  if (record.type === 'childList') {
    record.addedNodes.forEach(node => { if (node.isConnected) visit(node); });
    return;
  }
  const target = record.target;
  if (!target.isConnected) return;
  if (record.type === 'characterData') {
    if (!textExcluded(target.parentElement)) translateText(target as Text);
  } else if (record.attributeName && !attributesExcluded(target as Element)) {
    translateAttribute(target as Element, record.attributeName);
  }
}

function translateText(node: Text) {
  const value = node.data;
  const memo = texts.get(node);
  if (memo && value === memo.shown) return;
  const shown = hasChinese(value) ? toEnglish(value) : value;
  if (shown === value) { texts.delete(node); return; }
  texts.set(node, { source: value, shown });
  node.data = shown;
}

function translateAttribute(element: Element, name: string) {
  const value = element.getAttribute(name);
  let memos = attributes.get(element);
  const memo = memos?.get(name);
  if (memo && value === memo.shown) return;
  const shown = value !== null && hasChinese(value) ? toEnglish(value) : value;
  if (value === null || shown === null || shown === value) { memos?.delete(name); return; }
  if (!memos) attributes.set(element, memos = new Map());
  memos.set(name, { source: value, shown });
  element.setAttribute(name, shown);
}

function restore(root: Element) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  for (let node: Node | null = walker.currentNode; node; node = walker.nextNode()) {
    if (node.nodeType === Node.TEXT_NODE) {
      const text = node as Text;
      const memo = texts.get(text);
      if (!memo) continue;
      if (text.data === memo.shown) text.data = memo.source;
      texts.delete(text);
      continue;
    }
    const element = node as Element;
    const memos = attributes.get(element);
    if (!memos) continue;
    memos.forEach((memo, name) => { if (element.getAttribute(name) === memo.shown) element.setAttribute(name, memo.source); });
    attributes.delete(element);
  }
}

// Imported first in main.tsx: the observer is active before React's first commit, so English
// replaces the Chinese source before the first paint.
if (language === 'en') apply();
