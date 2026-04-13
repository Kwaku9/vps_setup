uniform sampler2D colorTexture;
uniform float time;
in vec2 v_textureCoordinates;

// Simple hash-based noise
float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

void main() {
    vec2 uv = v_textureCoordinates;
    vec3 color = texture(colorTexture, uv).rgb;

    // Convert to luminance
    float lum = dot(color, vec3(0.299, 0.587, 0.114));

    // Boost brightness
    lum = pow(lum, 0.7) * 1.4;

    // Green channel mapping (NVG phosphor)
    vec3 nvg = vec3(lum * 0.1, lum * 1.0, lum * 0.1);

    // Animated noise grain
    float noise = hash(uv * 500.0 + time * 10.0) * 0.08;
    nvg += noise;

    // Vignette (circular, stronger than CRT)
    vec2 center = uv - 0.5;
    float r2 = dot(center, center);
    float vignette = smoothstep(0.5, 0.2, sqrt(r2));
    nvg *= vignette;

    out_FragColor = vec4(nvg, 1.0);
}
