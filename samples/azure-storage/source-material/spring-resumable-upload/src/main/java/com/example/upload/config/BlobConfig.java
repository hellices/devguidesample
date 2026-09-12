package com.example.upload.config;

import com.azure.identity.DefaultAzureCredentialBuilder;
import com.azure.storage.blob.BlobContainerClient;
import com.azure.storage.blob.BlobServiceClientBuilder;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class BlobConfig {

    @Value("${azure.storage.account-name}")
    private String accountName;

    @Value("${azure.storage.container}")
    private String container;

    @Bean
    public BlobContainerClient blobContainerClient() {
        String endpoint = "https://" + accountName + ".blob.core.windows.net";
        BlobContainerClient client = new BlobServiceClientBuilder()
                .endpoint(endpoint)
                .credential(new DefaultAzureCredentialBuilder().build())
                .buildClient()
                .getBlobContainerClient(container);
        if (!client.exists()) {
            client.create();
        }
        return client;
    }
}
