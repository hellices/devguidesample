/**
 * CosmosDB Handler - Point Read 최적화 패턴
 * 
 * 이 핸들러는 CosmosDB의 Point Read를 활용하여
 * 효율적이고 재사용 가능한 데이터 접근 계층을 제공합니다.
 */

import { CosmosClient } from '@azure/cosmos';

/**
 * CosmosDB Handler 클래스
 * Point Read와 Query를 추상화하여 효율적인 데이터 접근 제공
 */
class CosmosHandler {
    /**
     * @param {CosmosClient} client - CosmosDB 클라이언트
     * @param {string} databaseId - 데이터베이스 ID
     * @param {string} containerId - 컨테이너 ID
     * @param {Object} options - 옵션
     * @param {boolean} options.enableLogging - 로깅 활성화
     * @param {Function} options.partitionKeyExtractor - Partition Key 추출 함수
     */
    constructor(client, databaseId, containerId, options = {}) {
        this.client = client;
        this.database = client.database(databaseId);
        this.container = this.database.container(containerId);
        this.databaseId = databaseId;
        this.containerId = containerId;
        this.enableLogging = options.enableLogging || false;
        this.partitionKeyExtractor = options.partitionKeyExtractor || ((item) => item.id);
    }

    /**
     * Point Read로 단일 문서 조회
     * 
     * @param {string} id - 문서 ID
     * @param {string|Array} partitionKey - Partition Key 값
     * @returns {Promise<Object|null>} 문서 또는 null
     */
    async getById(id, partitionKey) {
        try {
            const startTime = Date.now();
            const { resource, requestCharge } = await this.container
                .item(id, partitionKey)
                .read();
            
            if (this.enableLogging) {
                this.log('Point Read', {
                    id,
                    partitionKey,
                    duration: Date.now() - startTime,
                    requestCharge
                });
            }
            
            return resource;
        } catch (error) {
            if (error.code === 404) {
                return null;
            }
            throw this.wrapError('getById', error);
        }
    }

    /**
     * 여러 문서를 Point Read로 일괄 조회
     * 병렬 처리로 성능 최적화
     * 
     * @param {Array<{id: string, partitionKey: string|Array}>} items
     * @returns {Promise<Array>} 조회된 문서 배열
     */
    async getByIds(items) {
        const startTime = Date.now();
        
        const promises = items.map(({ id, partitionKey }) => 
            this.getById(id, partitionKey)
        );
        
        const results = await Promise.all(promises);
        const filteredResults = results.filter(item => item !== null);
        
        if (this.enableLogging) {
            this.log('Batch Point Read', {
                requestedCount: items.length,
                foundCount: filteredResults.length,
                duration: Date.now() - startTime
            });
        }
        
        return filteredResults;
    }

    /**
     * Point Read로 문서 존재 여부 확인
     * 
     * @param {string} id
     * @param {string|Array} partitionKey
     * @returns {Promise<boolean>}
     */
    async exists(id, partitionKey) {
        const item = await this.getById(id, partitionKey);
        return item !== null;
    }

    /**
     * 문서 생성 (Upsert)
     * 
     * @param {Object} item - 생성할 문서
     * @returns {Promise<Object>} 생성된 문서
     */
    async create(item) {
        try {
            const startTime = Date.now();
            const { resource, requestCharge } = await this.container.items.create(item);
            
            if (this.enableLogging) {
                this.log('Create', {
                    id: item.id,
                    duration: Date.now() - startTime,
                    requestCharge
                });
            }
            
            return resource;
        } catch (error) {
            throw this.wrapError('create', error);
        }
    }

    /**
     * 문서 업데이트 (Replace)
     * 
     * @param {string} id
     * @param {string|Array} partitionKey
     * @param {Object} updatedItem
     * @returns {Promise<Object>}
     */
    async update(id, partitionKey, updatedItem) {
        try {
            const startTime = Date.now();
            const { resource, requestCharge } = await this.container
                .item(id, partitionKey)
                .replace(updatedItem);
            
            if (this.enableLogging) {
                this.log('Update', {
                    id,
                    partitionKey,
                    duration: Date.now() - startTime,
                    requestCharge
                });
            }
            
            return resource;
        } catch (error) {
            throw this.wrapError('update', error);
        }
    }

    /**
     * 문서 삭제
     * 
     * @param {string} id
     * @param {string|Array} partitionKey
     * @returns {Promise<boolean>} 삭제 성공 여부
     */
    async delete(id, partitionKey) {
        try {
            const startTime = Date.now();
            const { requestCharge } = await this.container
                .item(id, partitionKey)
                .delete();
            
            if (this.enableLogging) {
                this.log('Delete', {
                    id,
                    partitionKey,
                    duration: Date.now() - startTime,
                    requestCharge
                });
            }
            
            return true;
        } catch (error) {
            if (error.code === 404) {
                return false;
            }
            throw this.wrapError('delete', error);
        }
    }

    /**
     * Query 실행 (Point Read를 사용할 수 없는 경우)
     * 
     * @param {Object} querySpec - SQL 쿼리 스펙
     * @param {string|Array} partitionKey - 선택적, 없으면 cross-partition query
     * @returns {Promise<Array>}
     */
    async query(querySpec, partitionKey = undefined) {
        try {
            const startTime = Date.now();
            const options = partitionKey ? { partitionKey } : {};
            
            const { resources, requestCharge } = await this.container.items
                .query(querySpec, options)
                .fetchAll();
            
            if (this.enableLogging) {
                this.log('Query', {
                    query: querySpec.query,
                    partitionKey: partitionKey || 'cross-partition',
                    resultCount: resources.length,
                    duration: Date.now() - startTime,
                    requestCharge
                });
            }
            
            return resources;
        } catch (error) {
            throw this.wrapError('query', error);
        }
    }

    /**
     * 하이브리드 접근: Partition Key가 있으면 Point Read, 없으면 Query
     * 
     * @param {string} id
     * @param {string|Array|null} partitionKey
     * @returns {Promise<Object|null>}
     */
    async get(id, partitionKey = null) {
        if (partitionKey) {
            // Point Read 사용
            return await this.getById(id, partitionKey);
        } else {
            // Query Fallback
            if (this.enableLogging) {
                console.warn(`Using Query instead of Point Read for id: ${id} - Consider providing partition key`);
            }
            
            const querySpec = {
                query: 'SELECT * FROM c WHERE c.id = @id',
                parameters: [{ name: '@id', value: id }]
            };
            
            const results = await this.query(querySpec);
            return results[0] || null;
        }
    }

    /**
     * 로깅 헬퍼
     */
    log(operation, details) {
        console.log(`[CosmosHandler] ${operation}:`, {
            container: this.containerId,
            ...details
        });
    }

    /**
     * 에러 래핑
     */
    wrapError(operation, error) {
        return new Error(`CosmosHandler.${operation} failed: ${error.message}`);
    }
}

/**
 * 캐싱 기능이 추가된 CosmosHandler
 * Partition Key를 캐싱하여 Query 사용을 최소화
 */
class CachedCosmosHandler extends CosmosHandler {
    constructor(client, databaseId, containerId, options = {}) {
        super(client, databaseId, containerId, options);
        this.cache = new Map();
        this.cacheTTL = options.cacheTTL || 300000; // 5분 기본값
        this.cacheMaxSize = options.cacheMaxSize || 10000;
    }

    /**
     * Partition Key를 캐싱하여 Point Read 최적화
     */
    async getById(id, partitionKey = null) {
        // Partition Key가 제공되면 일반 Point Read
        if (partitionKey) {
            const item = await super.getById(id, partitionKey);
            if (item) {
                this.cachePartitionKey(id, partitionKey);
            }
            return item;
        }

        // 캐시에서 Partition Key 조회
        const cachedPartitionKey = this.getCachedPartitionKey(id);
        if (cachedPartitionKey) {
            return await super.getById(id, cachedPartitionKey);
        }

        // Fallback: Query 사용
        const item = await super.get(id, null);
        if (item) {
            const pk = this.partitionKeyExtractor(item);
            this.cachePartitionKey(id, pk);
        }
        return item;
    }

    /**
     * Partition Key 캐싱
     */
    cachePartitionKey(id, partitionKey) {
        // 캐시 크기 제한
        if (this.cache.size >= this.cacheMaxSize) {
            // LRU: 가장 오래된 항목 제거
            const firstKey = this.cache.keys().next().value;
            this.cache.delete(firstKey);
        }

        this.cache.set(id, {
            partitionKey,
            expires: Date.now() + this.cacheTTL
        });
    }

    /**
     * 캐시에서 Partition Key 조회
     */
    getCachedPartitionKey(id) {
        const cached = this.cache.get(id);
        if (cached && cached.expires > Date.now()) {
            return cached.partitionKey;
        }
        this.cache.delete(id);
        return null;
    }

    /**
     * 캐시 통계
     */
    getCacheStats() {
        return {
            size: this.cache.size,
            maxSize: this.cacheMaxSize
        };
    }

    /**
     * 캐시 초기화
     */
    clearCache() {
        this.cache.clear();
    }
}

// ============================================
// 사용 예시
// ============================================

async function example() {
    const endpoint = process.env.COSMOS_ENDPOINT;
    const key = process.env.COSMOS_KEY;
    
    const client = new CosmosClient({ endpoint, key });
    
    // 기본 Handler
    const userHandler = new CosmosHandler(
        client, 
        'sampleDatabase', 
        'users',
        { enableLogging: true }
    );
    
    // Point Read
    const user = await userHandler.getById('user123', 'user123');
    console.log('User:', user);
    
    // 일괄 조회
    const users = await userHandler.getByIds([
        { id: 'user123', partitionKey: 'user123' },
        { id: 'user456', partitionKey: 'user456' }
    ]);
    console.log('Users:', users);
    
    // 생성
    const newUser = await userHandler.create({
        id: 'user999',
        name: 'New User',
        email: 'new@example.com'
    });
    
    // 업데이트
    const updated = await userHandler.update('user999', 'user999', {
        ...newUser,
        name: 'Updated User'
    });
    
    // 삭제
    await userHandler.delete('user999', 'user999');
    
    // 캐싱 Handler
    const cachedHandler = new CachedCosmosHandler(
        client,
        'sampleDatabase',
        'users',
        { enableLogging: true, cacheTTL: 600000 }
    );
    
    // 첫 번째 호출: Query 사용 (Partition Key 없음)
    const user1 = await cachedHandler.getById('user123');
    
    // 두 번째 호출: Point Read 사용 (캐시된 Partition Key 활용)
    const user2 = await cachedHandler.getById('user123');
    
    console.log('Cache Stats:', cachedHandler.getCacheStats());
}

// 모듈로 export
export { CosmosHandler, CachedCosmosHandler };
