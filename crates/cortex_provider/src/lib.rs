//! Provider/model capability registry independent of concrete provider hosts.

use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ProviderCapability {
    Text,
    Tools,
    Vision,
    Embeddings,
    ImageGeneration,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ProviderDescriptor {
    pub id: String,
    pub display_name: String,
    pub local: bool,
    pub capabilities: Vec<ProviderCapability>,
}

#[derive(Clone, Debug, Default)]
pub struct ProviderCatalog {
    providers: Vec<ProviderDescriptor>,
}

impl ProviderCatalog {
    pub fn register(&mut self, provider: ProviderDescriptor) {
        self.providers.retain(|item| item.id != provider.id);
        self.providers.push(provider);
        self.providers.sort_by(|a, b| a.id.cmp(&b.id));
    }
    pub fn list(&self) -> &[ProviderDescriptor] {
        &self.providers
    }
    pub fn get(&self, id: &str) -> Option<&ProviderDescriptor> {
        self.providers.iter().find(|item| item.id == id)
    }
}
