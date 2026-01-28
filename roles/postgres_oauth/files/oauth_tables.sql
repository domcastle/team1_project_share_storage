-- OAuth users
CREATE TABLE IF NOT EXISTS oauth_users (
  user_id VARCHAR(255) PRIMARY KEY,
  google_id VARCHAR(255) UNIQUE NOT NULL,
  email VARCHAR(255) UNIQUE NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- OAuth tokens
CREATE TABLE IF NOT EXISTS oauth_tokens (
  token_id SERIAL PRIMARY KEY,
  user_id VARCHAR(255) NOT NULL UNIQUE,
  access_token TEXT NOT NULL,
  refresh_token TEXT,
  expires_at TIMESTAMP NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_oauth_user
    FOREIGN KEY (user_id)
    REFERENCES oauth_users(user_id)
    ON DELETE CASCADE
);

