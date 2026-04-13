uniform sampler2D colorTexture;
in vec2 v_textureCoordinates;

// False-color thermal LUT: black → blue → magenta → yellow → white
vec3 thermalLUT(float t) {
    if (t < 0.25) {
        return mix(vec3(0.0), vec3(0.0, 0.0, 0.8), t * 4.0);
    } else if (t < 0.5) {
        return mix(vec3(0.0, 0.0, 0.8), vec3(0.8, 0.0, 0.8), (t - 0.25) * 4.0);
    } else if (t < 0.75) {
        return mix(vec3(0.8, 0.0, 0.8), vec3(1.0, 1.0, 0.0), (t - 0.5) * 4.0);
    } else {
        return mix(vec3(1.0, 1.0, 0.0), vec3(1.0, 1.0, 1.0), (t - 0.75) * 4.0);
    }
}

void main() {
    vec2 uv = v_textureCoordinates;

    // Pixelation effect (simulates low-res thermal sensor)
    float pixelSize = 400.0;
    vec2 pixelated = floor(uv * pixelSize) / pixelSize;

    vec3 color = texture(colorTexture, pixelated).rgb;

    // Luminance as temperature proxy
    float temp = dot(color, vec3(0.299, 0.587, 0.114));
    temp = clamp(temp, 0.0, 1.0);

    // Apply thermal LUT
    vec3 thermal = thermalLUT(temp);

    out_FragColor = vec4(thermal, 1.0);
}
