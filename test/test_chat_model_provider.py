import os
import unittest
from unittest.mock import patch

from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from career_agent import config
from career_agent.config import Settings
from career_agent.runtime import create_chat_model, create_embeddings


REQUIRED_ENVIRONMENT = {
    "GOOGLE_API_KEY": "key",
    "MONGODB_URI": "mongodb://unused",
    "MONGODB_DATABASE": "unused",
    "MONGODB_COLLECTION": "unused",
    "ATLAS_VECTOR_SEARCH_INDEX_NAME": "unused",
}


def load_settings_from(environment):
    with patch.dict(os.environ, environment, clear=True), patch.object(config, "load_dotenv"):
        return config.load_settings()


class GeminiConfigurationTests(unittest.TestCase):
    def test_defaults_apply_when_only_required_variables_are_set(self):
        settings = load_settings_from(REQUIRED_ENVIRONMENT)
        self.assertEqual(
            (settings.gemini_chat_model, settings.gemini_embedding_model, settings.embedding_dimensions),
            (config.DEFAULT_CHAT_MODEL, config.DEFAULT_EMBEDDING_MODEL, config.DEFAULT_EMBEDDING_DIMENSIONS),
        )

    def test_missing_api_key_is_reported(self):
        environment = {name: value for name, value in REQUIRED_ENVIRONMENT.items() if name != "GOOGLE_API_KEY"}
        with self.assertRaisesRegex(RuntimeError, "GOOGLE_API_KEY"):
            load_settings_from(environment)

    def test_models_use_configured_names_key_and_dimensions(self):
        settings = Settings("key", "unused", "unused", "unused", "unused", gemini_chat_model="chat-test", gemini_embedding_model="embedding-test", embedding_dimensions=256)
        chat_model = create_chat_model(settings)
        embeddings = create_embeddings(settings)
        models = [chat_model.runnable, *chat_model.fallbacks]
        self.assertTrue(all(isinstance(model, ChatGoogleGenerativeAI) for model in models))
        self.assertEqual([model.model for model in models], ["chat-test", config.DEFAULT_FALLBACK_CHAT_MODEL])
        self.assertTrue(all(model.google_api_key.get_secret_value() == "key" and model.timeout for model in models))
        self.assertIsInstance(embeddings, GoogleGenerativeAIEmbeddings)
        self.assertEqual(embeddings.output_dimensionality, 256)
        self.assertIn("embedding-test", embeddings.model)


if __name__ == "__main__":
    unittest.main()
