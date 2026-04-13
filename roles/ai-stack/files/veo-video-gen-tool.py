"""
title: Veo Video Generator
author: AICORTEX
description: Generates videos using Google Veo (2/3/3.1) via the Gemini API. Supports text-to-video and image-to-video with inline playback.
requirements: requests
version: 1.0.0
license: MIT
"""

import asyncio
import base64
import re
from typing import Any, Callable, Optional

import requests
from pydantic import BaseModel, Field


class EventEmitter:
    def __init__(self, event_emitter: Callable[[dict], Any] = None):
        self.event_emitter = event_emitter

    async def progress_update(self, description):
        await self.emit(description)

    async def error_update(self, description):
        await self.emit(description, "error", True)

    async def success_update(self, description):
        await self.emit(description, "success", True)

    async def emit(self, description="Unknown State", status="in_progress", done=False):
        if self.event_emitter:
            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "status": status,
                        "description": description,
                        "done": done,
                    },
                }
            )


class Tools:
    class Valves(BaseModel):
        GOOGLE_API_KEY: str = Field(
            default="", description="Google Gemini API key for Veo."
        )
        BASE_URL: str = Field(
            default="https://generativelanguage.googleapis.com/v1beta",
            description="Gemini API base URL.",
        )
        DEFAULT_MODEL: str = Field(
            default="veo-3.0-generate-001",
            description="Default Veo model. Options: veo-2.0-generate-001, veo-3.0-generate-001, veo-3.0-fast-generate-001, veo-3.1-generate-001, veo-3.1-fast-generate-001",
        )
        CITATION: bool = Field(
            default=True, description="Include citations in response."
        )

    def __init__(self):
        self.valves = self.Valves()
        self.citation = self.valves.CITATION

    def _download_video_as_data_url(self, uri: str) -> Optional[str]:
        """Download video from Google API and return as base64 data URL."""
        # Append API key for authentication
        separator = "&" if "?" in uri else "?"
        download_url = f"{uri}{separator}key={self.valves.GOOGLE_API_KEY}"
        resp = requests.get(download_url, timeout=120)
        if resp.status_code != 200:
            return None
        content_type = resp.headers.get("Content-Type", "video/mp4")
        b64 = base64.b64encode(resp.content).decode("utf-8")
        return f"data:{content_type};base64,{b64}"

    async def generate_video(
        self,
        prompt: str,
        model: Optional[str] = None,
        aspect_ratio: str = "16:9",
        negative_prompt: Optional[str] = None,
        person_generation: str = "allow_adult",
        number_of_videos: int = 1,
        duration_seconds: int = 8,
        generate_audio: bool = True,
        image: Optional[str] = None,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        Generate a video using Google Veo from a text prompt or image.

        :param prompt: Text description of the video to generate. Required unless image is provided.
        :param model: Veo model to use. Options: veo-2.0-generate-001, veo-3.0-generate-001, veo-3.0-fast-generate-001, veo-3.1-generate-001, veo-3.1-fast-generate-001. Defaults to valve setting.
        :param aspect_ratio: Video aspect ratio: "16:9" or "9:16". Default "16:9".
        :param negative_prompt: What to avoid generating in the video.
        :param person_generation: People in video: "dont_allow", "allow_adult", "allow_all". Default "allow_adult".
        :param number_of_videos: Number of videos to generate (1 or 2). Default 1.
        :param duration_seconds: Video length in seconds (5-8). Default 8.
        :param generate_audio: Generate audio track (Veo 3+ only, ignored for Veo 2). Default true.
        :param image: Optional image URL or base64 to use as first frame (image-to-video).
        :return: Status message. Videos are embedded inline via event emitter.
        """
        emitter = EventEmitter(__event_emitter__)

        try:
            if not prompt and not image:
                raise Exception("Either prompt or image must be provided.")

            if not self.valves.GOOGLE_API_KEY:
                raise Exception(
                    "No Google API key set. Configure GOOGLE_API_KEY in tool Valves."
                )

            selected_model = model or self.valves.DEFAULT_MODEL

            valid_models = [
                "veo-2.0-generate-001",
                "veo-3.0-generate-001",
                "veo-3.0-fast-generate-001",
                "veo-3.1-generate-001",
                "veo-3.1-fast-generate-001",
            ]
            if selected_model not in valid_models:
                raise Exception(
                    f"Invalid model: {selected_model}. Must be one of: {', '.join(valid_models)}"
                )

            if aspect_ratio not in ["16:9", "9:16"]:
                raise Exception("aspect_ratio must be '16:9' or '9:16'.")

            if number_of_videos not in [1, 2]:
                raise Exception("number_of_videos must be 1 or 2.")

            if duration_seconds < 5 or duration_seconds > 8:
                raise Exception("duration_seconds must be between 5 and 8.")

            is_veo3_plus = "veo-3" in selected_model

            await emitter.progress_update(
                f"Starting {selected_model} — '{prompt[:80]}...'" if len(prompt) > 80 else f"Starting {selected_model} — '{prompt}'"
            )

            # Build request payload
            instance = {}
            if prompt:
                instance["prompt"] = prompt
            if image:
                instance["image"] = image

            parameters = {
                "aspectRatio": aspect_ratio,
                "personGeneration": person_generation,
                "sampleCount": number_of_videos,
                "durationSeconds": duration_seconds,
            }

            if negative_prompt:
                parameters["negativePrompt"] = negative_prompt

            # Veo 3+ supports audio generation
            if is_veo3_plus:
                parameters["generateAudio"] = generate_audio

            data = {"instances": [instance], "parameters": parameters}

            # Initiate generation
            await emitter.progress_update("Submitting to Veo API...")
            url = f"{self.valves.BASE_URL}/models/{selected_model}:predictLongRunning?key={self.valves.GOOGLE_API_KEY}"
            response = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json=data,
                timeout=30,
            )

            if response.status_code != 200:
                raise Exception(
                    f"API returned {response.status_code}: {response.text[:500]}"
                )

            operation_name = response.json().get("name")
            if not operation_name:
                raise Exception("No operation name in API response.")

            await emitter.progress_update(
                "Video generating — polling for completion (may take several minutes)..."
            )

            # Poll for completion
            max_checks = 120  # 10 minutes at 5s intervals
            for check in range(1, max_checks + 1):
                await asyncio.sleep(5)

                check_url = f"{self.valves.BASE_URL}/{operation_name}?key={self.valves.GOOGLE_API_KEY}"
                check_resp = requests.get(check_url, timeout=30)

                if check_resp.status_code != 200:
                    raise Exception(
                        f"Status check failed: {check_resp.status_code}"
                    )

                status_data = check_resp.json()

                if not status_data.get("done", False):
                    if check % 6 == 0:  # Update every 30s
                        await emitter.progress_update(
                            f"Still generating... ({check * 5}s elapsed)"
                        )
                    continue

                # Done — check for errors
                if "error" in status_data:
                    error_msg = status_data["error"].get("message", "Unknown error")
                    raise Exception(f"Veo generation failed: {error_msg}")

                # Extract video URIs
                gen_response = (
                    status_data.get("response", {})
                    .get("generateVideoResponse", {})
                )
                samples = gen_response.get("generatedSamples", [])

                if not samples:
                    raise Exception(
                        f"No videos in response. Raw: {str(status_data)[:500]}"
                    )

                await emitter.progress_update(
                    f"Downloading {len(samples)} video(s)..."
                )

                # Download each video and emit inline
                for i, sample in enumerate(samples):
                    uri = sample.get("video", {}).get("uri")
                    if not uri:
                        continue

                    data_url = self._download_video_as_data_url(uri)
                    if not data_url:
                        await emitter.progress_update(
                            f"Failed to download video {i + 1}, skipping."
                        )
                        continue

                    # Emit video as inline HTML with playback controls
                    await __event_emitter__(
                        {
                            "type": "message",
                            "data": {
                                "content": f'\n\n<video controls autoplay loop style="max-width:100%; border-radius:8px;">\n<source src="{data_url}" type="video/mp4">\nYour browser does not support the video tag.\n</video>\n\n'
                            },
                        }
                    )

                model_label = selected_model.replace("-generate-001", "").replace("-", " ").title()
                audio_note = " with audio" if is_veo3_plus and generate_audio else ""
                await emitter.success_update(
                    f"{len(samples)} video(s) generated with {model_label}{audio_note}."
                )
                return f"Generated {len(samples)} video(s) using {model_label}{audio_note} for prompt: {prompt}"

            raise Exception("Timed out after 10 minutes. Generation may still be running.")

        except Exception as e:
            error_message = f"Error: {str(e)}"
            await emitter.error_update(error_message)
            return error_message
