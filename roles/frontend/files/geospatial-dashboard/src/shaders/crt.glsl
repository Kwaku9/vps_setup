uniform sampler2D colorTexture;
uniform float time;
in vec2 v_textureCoordinates;

void main() {
    vec2 uv = v_textureCoordinates;

    // Barrel distortion
    vec2 center = uv - 0.5;
    float r2 = dot(center, center);
    uv = uv + center * r2 * 0.15;

    // Chromatic aberration
    float offset = 0.002;
    float r = texture(colorTexture, uv + vec2(offset, 0.0)).r;
    float g = texture(colorTexture, uv).g;
    float b = texture(colorTexture, uv - vec2(offset, 0.0)).b;
    vec3 color = vec3(r, g, b);

    // Scanlines
    float scanline = sin(uv.y * 800.0) * 0.08;
    color -= scanline;

    // Phosphor glow
    color *= 1.0 + 0.03 * sin(time * 2.0);

    // Vignette
    float vignette = 1.0 - r2 * 1.5;
    color *= vignette;

    // Slight green tint
    color *= vec3(0.9, 1.0, 0.9);

    out_FragColor = vec4(color, 1.0);
}
