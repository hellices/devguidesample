/**
 * 간단한 CosmosDB Point Read 예제
 * 
 * Point Read는 ID와 Partition Key를 정확히 알고 있을 때 사용하는
 * 가장 효율적인 CosmosDB 읽기 방식입니다.
 */

import { CosmosClient } from '@azure/cosmos';

// CosmosDB 연결 설정
const endpoint = process.env.COSMOS_ENDPOINT;
const key = process.env.COSMOS_KEY;

const client = new CosmosClient({ endpoint, key });
const database = client.database('sampleDatabase');
const container = database.container('users');

/**
 * Point Read를 사용한 단일 문서 조회
 * 
 * @param {string} id - 문서 ID
 * @param {string} partitionKey - Partition Key 값
 * @returns {Promise<Object|null>} 문서 또는 null
 */
async function getUserByPointRead(id, partitionKey) {
    try {
        // Point Read: 가장 효율적 (약 1 RU)
        const { resource: user, requestCharge } = await container
            .item(id, partitionKey)
            .read();
        
        console.log(`Point Read - RU Consumed: ${requestCharge}`);
        return user;
    } catch (error) {
        if (error.code === 404) {
            console.log(`User not found: ${id}`);
            return null;
        }
        console.error('Error in point read:', error.message);
        throw error;
    }
}

/**
 * Query를 사용한 문서 조회 (비교용)
 * Point Read보다 비효율적임
 * 
 * @param {string} id - 문서 ID
 * @returns {Promise<Object|null>}
 */
async function getUserByQuery(id) {
    try {
        // Query: 비효율적 (약 3-10 RU)
        const querySpec = {
            query: 'SELECT * FROM c WHERE c.id = @id',
            parameters: [{ name: '@id', value: id }]
        };
        
        const { resources, requestCharge } = await container.items
            .query(querySpec)
            .fetchAll();
        
        console.log(`Query - RU Consumed: ${requestCharge}`);
        return resources[0] || null;
    } catch (error) {
        console.error('Error in query:', error.message);
        throw error;
    }
}

/**
 * 여러 문서를 Point Read로 일괄 조회
 * 병렬 처리로 성능 최적화
 * 
 * @param {Array<{id: string, partitionKey: string}>} items
 * @returns {Promise<Array>}
 */
async function batchGetUsers(items) {
    const promises = items.map(({ id, partitionKey }) => 
        getUserByPointRead(id, partitionKey)
    );
    
    const results = await Promise.all(promises);
    
    // null 제거 (존재하지 않는 문서)
    return results.filter(user => user !== null);
}

/**
 * 문서 존재 여부 확인
 * 
 * @param {string} id
 * @param {string} partitionKey
 * @returns {Promise<boolean>}
 */
async function userExists(id, partitionKey) {
    const user = await getUserByPointRead(id, partitionKey);
    return user !== null;
}

/**
 * Point Read vs Query 성능 비교
 */
async function comparePerformance(userId) {
    console.log('\n=== Performance Comparison ===\n');
    
    // Point Read
    console.log('Testing Point Read...');
    const startPoint = Date.now();
    const userByPointRead = await getUserByPointRead(userId, userId);
    const pointReadTime = Date.now() - startPoint;
    console.log(`Point Read Time: ${pointReadTime}ms\n`);
    
    // Query
    console.log('Testing Query...');
    const startQuery = Date.now();
    const userByQuery = await getUserByQuery(userId);
    const queryTime = Date.now() - startQuery;
    console.log(`Query Time: ${queryTime}ms\n`);
    
    console.log('Performance Summary:');
    console.log(`- Point Read: ${pointReadTime}ms`);
    console.log(`- Query: ${queryTime}ms`);
    console.log(`- Speed Improvement: ${(queryTime / pointReadTime).toFixed(2)}x faster`);
}

// ============================================
// 사용 예시
// ============================================

async function main() {
    try {
        // 예시 1: 단일 사용자 조회 (Point Read)
        console.log('\n--- Example 1: Single User Point Read ---');
        const user = await getUserByPointRead('user123', 'user123');
        console.log('User:', user);
        
        // 예시 2: 일괄 조회
        console.log('\n--- Example 2: Batch Point Read ---');
        const users = await batchGetUsers([
            { id: 'user123', partitionKey: 'user123' },
            { id: 'user456', partitionKey: 'user456' },
            { id: 'user789', partitionKey: 'user789' }
        ]);
        console.log(`Found ${users.length} users`);
        
        // 예시 3: 존재 여부 확인
        console.log('\n--- Example 3: Check User Existence ---');
        const exists = await userExists('user123', 'user123');
        console.log(`User exists: ${exists}`);
        
        // 예시 4: 성능 비교
        await comparePerformance('user123');
        
    } catch (error) {
        console.error('Error in main:', error);
    }
}

// 실행
if (require.main === module) {
    main().catch(console.error);
}

// 모듈로 export
export {
    getUserByPointRead,
    getUserByQuery,
    batchGetUsers,
    userExists,
    comparePerformance
};
