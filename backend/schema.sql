CREATE TABLE IF NOT EXISTS conversations (
  id uuid PRIMARY KEY,
  account_name text NOT NULL UNIQUE,
  profile jsonb NOT NULL,
  onboarding jsonb NOT NULL,
  version bigint NOT NULL DEFAULT 0,
  next_sequence bigint NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS messages (
  id uuid PRIMARY KEY,
  conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  sequence bigint NOT NULL,
  role text NOT NULL CHECK (role IN ('user','assistant','internal')),
  modality text NOT NULL CHECK (modality IN ('text','voice','internal')),
  content text,
  visible boolean NOT NULL DEFAULT true,
  model_message jsonb,
  source_key text NOT NULL,
  call_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (conversation_id, sequence),
  UNIQUE (conversation_id, source_key)
);
CREATE INDEX IF NOT EXISTS messages_by_conversation ON messages(conversation_id, sequence);
CREATE TABLE IF NOT EXISTS operations (
  id uuid PRIMARY KEY,
  conversation_id uuid NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  source_key text NOT NULL,
  kind text NOT NULL,
  result jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (conversation_id, source_key)
);
