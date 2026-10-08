"use strict";
window.addEventListener("DOMContentLoaded", () => {
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
