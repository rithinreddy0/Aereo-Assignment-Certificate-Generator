"use strict";
window.addEventListener("DOMContentLoaded", () => {
  fetch("/ui-config")
    .then((response) => (response.ok ? response.json() : null))
    .then((config) => {
      if (config) {
        document.getElementById("docs-batch-limit").textContent =
          `${config.max_recipients.toLocaleString()} recipients`;
      }
    })
    .catch(() => {});
  SwaggerUIBundle({
    url: "/openapi.json",
    dom_id: "#swagger-ui",
    deepLinking: true,
    displayRequestDuration: true,
    defaultModelsExpandDepth: -1,
    docExpansion: "list",
    persistAuthorization: false,
    validatorUrl: null,
    presets: [SwaggerUIBundle.presets.apis],
  });
});
