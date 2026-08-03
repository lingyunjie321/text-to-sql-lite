import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SettingsLayout } from "./SettingsLayout";

describe("SettingsLayout", () => {
  it("mounts exactly one active model Profile section across desktop and mobile navigation", () => {
    const markup = renderToStaticMarkup(<SettingsLayout />);

    expect(
      markup.match(/data-settings-section="model-profiles"/g),
    ).toHaveLength(1);
  });
});
