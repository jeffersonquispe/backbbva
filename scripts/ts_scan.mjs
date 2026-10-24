#!/usr/bin/env node
// Structural scan of the frontend for scripts/build_project_graph.py.
//
// Usage: node scripts/ts_scan.mjs <frontend-dir>
// Prints JSON {relative/path.tsx: {...}} using the frontend's own TypeScript
// compiler (syntax only, no type-check), so "renders" and "calls" come from
// real JSX tags / identifier references instead of text matches.
import { createRequire } from "node:module";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";

const root = process.argv[2] ? resolve(process.argv[2]) : "";
if (!root) {
  console.error("usage: ts_scan.mjs <frontend-dir>");
  process.exit(2);
}
const ts = createRequire(join(root, "package.json"))("typescript");

const TEXT_ATTRS = new Set([
  "label", "title", "placeholder", "aria-label", "searchPlaceholder", "description",
  "itemLabel", "emptyLabel", "noMatchLabel", "heading",
]);
const TEXT_PROPS = new Set(["label", "header", "title", "description", "placeholder"]);
const ACTION_TAGS = new Set(["ActionButton", "ActionLink"]);
const CLICKABLE_TAGS = new Set(["button", "Button", "Link", "a"]);

function walkFiles(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walkFiles(full, out);
    else if (/\.tsx?$/.test(name)) out.push(full);
  }
  return out;
}

const looksLikeCode = (text) => /[=;(){}]|=>|className|\bimport\b|^\W/.test(text);
function usefulText(raw) {
  const text = raw.replace(/\s+/g, " ").trim();
  if (text.length < 3 || text.length > 90) return null;
  if (!/[A-Za-zÁÉÍÓÚáéíóúñÑ]{3}/.test(text) || looksLikeCode(text)) return null;
  return text;
}

function scan(file) {
  const source = readFileSync(file, "utf8");
  const sf = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, file.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const result = { imports: [], refs: new Set(), jsx: new Set(), texts: [], actions: [], links: [], route: null, comment: "" };
  const addText = (value) => {
    const text = usefulText(value);
    if (text && !result.texts.includes(text)) result.texts.push(text);
  };
  const addAction = (value) => {
    const text = usefulText(value);
    if (text && !result.actions.includes(text)) result.actions.push(text);
  };
  const strOf = (node) =>
    node && (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) ? node.text : null;

  const leading = ts.getLeadingCommentRanges(source, 0) ?? [];
  result.comment = leading
    .map((r) => source.slice(r.pos, r.end).replace(/^\/\*+|\*+\/$/gm, "").replace(/^\s*(\/\/|\*)\s?/gm, ""))
    .join(" ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 400);

  const visit = (node, inType) => {
    if (ts.isImportDeclaration(node)) {
      const names = [];
      const clause = node.importClause;
      if (clause && !clause.isTypeOnly) {
        if (clause.name) names.push(clause.name.text);
        const bindings = clause.namedBindings;
        if (bindings && ts.isNamedImports(bindings)) {
          for (const el of bindings.elements) if (!el.isTypeOnly) names.push(el.name.text);
        } else if (bindings && ts.isNamespaceImport(bindings)) names.push(bindings.name.text);
      }
      result.imports.push({ src: node.moduleSpecifier.text, names });
      return; // identifiers inside imports are not usages
    }
    const nowType = inType || ts.isTypeNode(node);
    if (ts.isIdentifier(node) && !nowType) result.refs.add(node.text);

    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName;
      const tagName = ts.isIdentifier(tag) ? tag.text : ts.isPropertyAccessExpression(tag) ? tag.expression.getText(sf) : tag.getText(sf);
      result.jsx.add(tagName.split(".")[0]);
      let label = null;
      let aria = null;
      for (const attr of node.attributes.properties) {
        if (!ts.isJsxAttribute(attr)) continue;
        const name = attr.name.getText(sf);
        const value = attr.initializer && ts.isJsxExpression(attr.initializer) ? strOf(attr.initializer.expression) : strOf(attr.initializer);
        if (value == null) continue;
        if (TEXT_ATTRS.has(name)) addText(value);
        if (name === "label") label = value;
        if (name === "aria-label") aria = value;
        if ((name === "to" || name === "href") && value.startsWith("/")) result.links.push(value);
      }
      const clickable = ACTION_TAGS.has(tagName) || CLICKABLE_TAGS.has(tagName);
      if (ACTION_TAGS.has(tagName) && label) addAction(label);
      else if (clickable && aria) addAction(aria);
      if (clickable && ts.isJsxOpeningElement(node) && ts.isJsxElement(node.parent)) {
        const text = node.parent.children.find((c) => ts.isJsxText(c) && c.text.trim());
        if (text && /^[A-ZÁÉÍÓÚÑ]/.test(text.text.trim())) addAction(text.text);
      }
    }
    if (ts.isJsxText(node)) addText(node.text);
    if (ts.isPropertyAssignment(node) && node.name && TEXT_PROPS.has(node.name.getText(sf))) {
      const value = strOf(node.initializer);
      if (value) addText(value);
    }
    if (ts.isCallExpression(node)) {
      const callee = node.expression;
      if (ts.isIdentifier(callee) && callee.text === "createFileRoute") {
        const path = strOf(node.arguments[0]);
        if (path) result.route = path;
      }
      if (ts.isIdentifier(callee) && callee.text === "navigate" && node.arguments[0] && ts.isObjectLiteralExpression(node.arguments[0])) {
        for (const prop of node.arguments[0].properties) {
          if (ts.isPropertyAssignment(prop) && prop.name.getText(sf) === "to") {
            const to = strOf(prop.initializer);
            if (to && to.startsWith("/")) result.links.push(to);
          }
        }
      }
    }
    ts.forEachChild(node, (child) => visit(child, nowType));
  };
  visit(sf, false);
  return { ...result, refs: [...result.refs].sort(), jsx: [...result.jsx].sort() };
}

const out = {};
for (const file of walkFiles(join(root, "src")).sort()) {
  const rel = relative(join(root, "src"), file).split("\\").join("/");
  if (rel.startsWith("test/") || /\.(test|spec)\.tsx?$/.test(rel) || rel === "routeTree.gen.ts") continue;
  out[rel] = scan(file);
}
process.stdout.write(JSON.stringify(out));
