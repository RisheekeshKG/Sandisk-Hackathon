"""
Configuration module for the Verilog Verification Agent
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Configuration settings for the agent"""
    
    # API Keys
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyA6jiUSFZzMJYDIiANqXeQxb44GDOe1llo")
    
    # Agent Settings
    MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "5"))
    
    # Model Settings
    MODEL_NAME = "gemini-2.5-flash"
    TEMPERATURE = 0.2
    
    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    @classmethod
    def validate(cls):
        """Validate that required configuration is present"""
        if not cls.GOOGLE_API_KEY:
            raise ValueError(
                "GOOGLE_API_KEY not found. "
                "Please set it in your .env file or environment variables."
            )
        return True

# Validate configuration on import
# Config.validate()

