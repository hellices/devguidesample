using './main.bicep'

param prefix = 'dbsim'
param location = 'koreacentral'
param mysqlAdminUser = 'simadmin'
param mysqlAdminPassword = ''   // 배포 시 --parameters mysqlAdminPassword=<value> 로 전달
param dbName = 'simdb'
param aksNodeCount = 2
param aksNodeSize = 'Standard_D2s_v3'
