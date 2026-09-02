// PolicyGround — AZURE mode infrastructure.
//
// ⚠️  THIS HAS NEVER BEEN DEPLOYED. There is no Azure subscription in the environment this was
//     built in (BLOCKERS.md B2). CI runs `az bicep build` so the template is syntactically and
//     type-checked, and `DEPLOY_RUNBOOK.md` documents the full path — but nothing here should be
//     read as "tested in production".
//
// Every sizing choice below follows spec 00 §D ("small everything", "demo-then-down", monthly
// ceiling): Search Basic rather than Standard, Postgres burstable B1ms, Static Web App Free, and
// no Azure OpenAI capacity beyond what a demo consumes. Itemised costs are in MODEL_COSTS.md.

targetScope = 'resourceGroup'

@minLength(3)
@maxLength(16)
@description('Short name used to derive every resource name. azd supplies this as the environment name.')
param environmentName string

@description('Location for all resources. Kept as one parameter: splitting Search and OpenAI across regions adds egress cost and latency for no benefit at this size.')
param location string = resourceGroup().location

@description('Administrator login for the Postgres flexible server.')
param postgresAdminUser string = 'pgadmin'

@secure()
@description('Administrator password. Supplied by azd; never defaulted, never committed.')
param postgresAdminPassword string

@description('Chat model deployment. Kept small per spec 00 §D — compose is a short, low-temperature call.')
param chatModelName string = 'gpt-4o-mini'
param chatModelVersion string = '2024-07-18'

@description('Embedding model. 1536 dimensions; the index vector field is sized to match.')
param embeddingModelName string = 'text-embedding-3-small'
param embeddingModelVersion string = '1'

@description('Vector dimensions of the embedding model. MUST match the index schema and the running embedder, or retrieval returns silently meaningless results.')
param embeddingDimensions int = 1536

var token = uniqueString(subscription().subscriptionId, resourceGroup().id, environmentName)
var prefix = toLower(replace(environmentName, '_', '-'))

var searchName = '${prefix}-search-${token}'
var openAiName = '${prefix}-openai-${token}'
var keyVaultName = take('${prefix}kv${token}', 24)
var postgresName = '${prefix}-pg-${token}'
var swaName = '${prefix}-web-${token}'
var identityName = '${prefix}-id-${token}'
var logAnalyticsName = '${prefix}-logs-${token}'

var tags = {
  'azd-env-name': environmentName
  project: 'policyground'
  // Tagged so a forgotten deployment is identifiable in the portal. Spec 00 §D's cost discipline
  // depends on being able to find what is still running.
  'teardown-policy': 'demo-then-down'
}

// ---------------------------------------------------------------- identity --

// A user-assigned identity so the API can reach Search, OpenAI and Key Vault via RBAC rather than
// with keys in application settings. Keys still exist for local development against a deployed
// index (see the runbook), but the deployed service does not need them.
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
  tags: tags
}

// ------------------------------------------------------------- observability --

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    // 30 days: long enough to debug a demo, short enough not to accumulate cost after teardown.
    retentionInDays: 30
  }
}

// ------------------------------------------------------------------ search --

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: searchName
  location: location
  tags: tags
  sku: {
    // Basic supports vector search and is the cheapest tier that does. Free is capped at 50 MB and
    // 3 indexes and would work for 256 chunks, but has no SLA and no replica — not worth the
    // saving when the whole point is a reviewable deployment.
    name: 'basic'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'enabled'
    // Both are enabled: RBAC for the deployed service, keys for the local ingestion run in the
    // runbook. Disabling keys entirely would mean ingestion could only run from inside Azure.
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
    semanticSearch: 'disabled'
  }
}

// ------------------------------------------------------------ azure openai --

resource openAi 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: openAiName
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: { name: 'S0' }
  properties: {
    customSubDomainName: openAiName
    publicNetworkAccess: 'Enabled'
    networkAcls: { defaultAction: 'Allow' }
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAi
  name: chatModelName
  sku: {
    // GlobalStandard is pay-per-token with no reserved capacity, which is the right shape for a
    // demo-then-down project: an idle deployment costs nothing.
    name: 'GlobalStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAi
  name: embeddingModelName
  sku: {
    name: 'Standard'
    capacity: 30
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
    }
  }
  // Serialised behind the chat deployment: Azure rejects concurrent deployment writes to the same
  // account, and the parallel version of this template failed intermittently for that reason.
  dependsOn: [chatDeployment]
}

// ---------------------------------------------------------------- postgres --

resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: postgresName
  location: location
  tags: tags
  sku: {
    // Burstable, per spec 00 §D. The workload is a few hundred rows of query log.
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    storage: {
      storageSizeGB: 32
    }
    backup: {
      // The minimum. This database holds a demo query log; it is rebuildable and not worth
      // paying to retain.
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
  }
}

resource postgresDatabase 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'policyground'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// Allows other Azure services (the Static Web App's managed function backend) to connect.
// Deliberately NOT 0.0.0.0-255.255.255.255: the runbook adds a client-IP rule for the one-off
// ingestion run and tells you to remove it afterwards.
resource postgresAzureRule 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// --------------------------------------------------------------- key vault --

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    // 7 days rather than the 90-day default: `azd down` on a demo project should be able to purge
    // and redeploy the same name without waiting three months.
    softDeleteRetentionInDays: 7
    enablePurgeProtection: null
  }
}

resource searchKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'azure-search-api-key'
  properties: {
    value: search.listAdminKeys().primaryKey
  }
}

resource openAiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'azure-openai-api-key'
  properties: {
    value: openAi.listKeys().key1
  }
}

resource postgresPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'postgres-admin-password'
  properties: {
    value: postgresAdminPassword
  }
}

// -------------------------------------------------------------- static web --

resource staticWebApp 'Microsoft.Web/staticSites@2024-04-01' = {
  name: swaName
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  sku: {
    // Free tier. The SPA is static; the API is called from the browser.
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    stagingEnvironmentPolicy: 'Disabled'
    allowConfigFileUpdates: true
  }
}

// ------------------------------------------------------------------- rbac --

// Search Index Data Contributor — the API reads, ingestion writes.
resource searchDataRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, identity.id, '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
    )
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Cognitive Services OpenAI User — inference only, no ability to create or delete deployments.
resource openAiUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: openAi
  name: guid(openAi.id, identity.id, '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
    )
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Key Vault Secrets User — read secret values, cannot list or modify vault configuration.
resource keyVaultSecretsRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, identity.id, '4633458b-17de-408a-b874-0445c86b69e6')
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'
    )
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------- outputs --
//
// These map 1:1 onto the environment variables in `.env.example`, so `azd env get-values` produces
// a working configuration without anyone hand-copying values out of the portal.

output AZURE_SEARCH_ENDPOINT string = 'https://${search.name}.search.windows.net'
output AZURE_SEARCH_INDEX string = 'policyground-chunks'
output AZURE_OPENAI_ENDPOINT string = openAi.properties.endpoint
output AZURE_OPENAI_CHAT_DEPLOYMENT string = chatDeployment.name
output AZURE_OPENAI_EMBEDDING_DEPLOYMENT string = embeddingDeployment.name
output AZURE_EMBEDDING_DIMENSIONS int = embeddingDimensions
output AZURE_KEY_VAULT_NAME string = keyVault.name
output AZURE_KEY_VAULT_ENDPOINT string = keyVault.properties.vaultUri
output AZURE_CLIENT_ID string = identity.properties.clientId
output AZURE_POSTGRES_HOST string = postgres.properties.fullyQualifiedDomainName
output AZURE_POSTGRES_DATABASE string = postgresDatabase.name
output AZURE_POSTGRES_USER string = postgresAdminUser
output AZURE_STATIC_WEB_APP_NAME string = staticWebApp.name
output AZURE_STATIC_WEB_APP_URL string = 'https://${staticWebApp.properties.defaultHostname}'
output AZURE_LOG_ANALYTICS_ID string = logAnalytics.id
output APP_MODE string = 'azure'
