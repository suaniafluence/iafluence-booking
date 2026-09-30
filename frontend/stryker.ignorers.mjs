// Stryker ignorer: Tailwind class strings are presentation only, mutating them is noise.
import { declareValuePlugin, PluginKind } from "@stryker-mutator/api/plugin";

export const strykerPlugins = [
  declareValuePlugin(PluginKind.Ignore, "tailwind-classes", {
    shouldIgnore(path) {
      if (path.isJSXAttribute() && path.node.name.name === "className") {
        return "CSS classes are not behaviour";
      }
    },
  }),
];
