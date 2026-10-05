import tempfile
import unittest
from pathlib import Path

from cache_models import link_models


FILES = {
    "qwen-image-2.1-UC-Q4_K_M.gguf": "diffusion_models/qwen-image-2.1-UC-Q4_K_M.gguf",
    "text_encoders/qwen3vl_8b_int8_convrot.safetensors": "text_encoders/qwen3vl_8b_int8_convrot.safetensors",
    "vae/qwen_image_2.1_vae_bf16.safetensors": "vae/qwen_image_2.1_vae_bf16.safetensors",
}


class CacheModelsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshot = self.root / "hub" / "snapshots" / "revision"
        self.models = self.root / "comfyui" / "models"
        # Real Hugging Face snapshots contain symlinks into a sibling blob store.
        for index, filename in enumerate(FILES):
            blob = self.root / "hub" / "blobs" / str(index)
            blob.parent.mkdir(parents=True, exist_ok=True)
            blob.write_bytes(f"model-{index}".encode())
            source = self.snapshot / filename
            source.parent.mkdir(parents=True, exist_ok=True)
            source.symlink_to(blob)

    def test_comfyui_can_read_all_three_models_from_the_mounted_cache(self):
        link_models(self.snapshot, self.models)
        for source_name, target_name in FILES.items():
            with self.subTest(model=source_name):
                source = self.snapshot / source_name
                target = self.models / target_name
                self.assertTrue(target.is_symlink())
                self.assertEqual(target.resolve(), source.resolve())
                self.assertEqual(target.read_bytes(), source.read_bytes())

    def test_restarting_with_correct_links_is_safe(self):
        link_models(self.snapshot, self.models)
        link_models(self.snapshot, self.models)
        for source_name, target_name in FILES.items():
            self.assertEqual(
                (self.models / target_name).read_bytes(),
                (self.snapshot / source_name).read_bytes(),
            )

    def test_missing_cache_fails_before_creating_any_model_links(self):
        missing = "vae/qwen_image_2.1_vae_bf16.safetensors"
        (self.snapshot / missing).unlink()
        with self.assertRaisesRegex(FileNotFoundError, "qwen_image_2.1_vae_bf16"):
            link_models(self.snapshot, self.models)
        self.assertFalse(self.models.exists())

    def test_existing_unrelated_model_is_not_overwritten(self):
        target = self.models / "vae/qwen_image_2.1_vae_bf16.safetensors"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"do not overwrite")
        with self.assertRaises(FileExistsError):
            link_models(self.snapshot, self.models)
        self.assertEqual(target.read_bytes(), b"do not overwrite")
        self.assertFalse((self.models / "diffusion_models").exists())


if __name__ == "__main__":
    unittest.main()
