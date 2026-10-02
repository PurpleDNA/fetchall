output "public_ip" {
  value = oci_core_public_ip.fetchall.ip_address
}

output "api_hostname" {
  value = "${replace(oci_core_public_ip.fetchall.ip_address, ".", "-")}.sslip.io"
}

output "ssh" {
  value = "ssh -i ~/.ssh/fetchall_oci ubuntu@${oci_core_public_ip.fetchall.ip_address}"
}
