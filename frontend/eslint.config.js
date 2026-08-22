import js from '@eslint/js'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'

export default [
  js.configs.recommended,
  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser, ...globals.es2021 },
    },
    plugins: { react, 'react-hooks': reactHooks },
    settings: { react: { version: 'detect' } },
    rules: {
      ...react.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'react/react-in-jsx-scope': 'off', // React 19 automatic JSX runtime
      'react/prop-types': 'off', // no PropTypes in this codebase
      // useEffect(refresh, []) passes refresh's return value straight
      // through as the effect's cleanup function. When refresh is async
      // that's a Promise, and React throws trying to call it on unmount
      // (the "Manage chores" blank-page bug — see mount-unmount.test.jsx).
      // Requiring an inline arrow keeps the return value under control.
      'no-restricted-syntax': [
        'error',
        {
          selector:
            "CallExpression[callee.name='useEffect'] > Identifier.arguments:first-child",
          message:
            'Pass an inline () => { ... } to useEffect, not a function reference — ' +
            'if the referenced function returns a Promise, React calls it as the ' +
            'cleanup function on unmount and throws.',
        },
      ],
    },
  },
  {
    files: ['**/*.test.{js,jsx}'],
    languageOptions: { globals: { ...globals.node } },
  },
  { ignores: ['dist/**', 'node_modules/**'] },
]
