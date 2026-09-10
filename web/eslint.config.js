// @ts-check
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "playwright-report", "test-results"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: { ecmaVersion: 2022, globals: { ...globals.browser, ...globals.node } },
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // los componentes exportan sus helpers al lado a proposito; Fast Refresh no es lo que se cuida aca
      "react-refresh/only-export-components": "off",
      // las tres reglas del compilador de React marcan idiomas que este codigo usa a conciencia
      // ("latest ref" asignado en render, setState al abrir un efecto, Date.now para "hace X"):
      // se ven como advertencia, no frenan el lint
      "react-hooks/refs": "warn",
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/purity": "warn",
      // el codigo usa `_x` para lo que se ignora a proposito
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
      // los tests de node importan "./x.ts" con extension (TS5097) y lo tapan con @ts-ignore explicado
      "@typescript-eslint/ban-ts-comment": ["error", { "ts-ignore": "allow-with-description" }],
    },
  },
  {
    files: ["**/*.test.ts", "tests-ui/**/*.ts"],
    rules: { "@typescript-eslint/no-explicit-any": "off" },
  },
);
